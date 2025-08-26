# modules/antispam.py
from __future__ import annotations
import re
import time
from datetime import timedelta
from typing import Tuple, Optional

from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from telebot.apihelper import ApiTelegramException

from state import GROUP_SETTINGS, PENDING_INPUT
from utils import is_user_admin

# ------------- Safe edit wrapper -------------
def _safe_edit_text(bot, *args, **kwargs):
    try:
        return bot.edit_message_text(*args, **kwargs)
    except ApiTelegramException as e:
        if 'message is not modified' in str(e).lower():
            return
        raise
    except Exception as e:
        if 'message is not modified' in str(e).lower():
            return
        raise

# ------------- Defaults / persist -------------
DEFAULT_ANTISPAM = {
    "enabled": True,

    # Telegram links submenu
    "tg_links": {
        "penalty": "off",             # off|warn|kick|mute|ban
        "delete": False,
        "username_antispam": True,
        "bots_antispam": True,
        "mute_secs": 30*60,
        "warn_secs": 30*60,
        "ban_secs":  30*60,
    },

    # Forwarding submenu (per-scope + durations)
    "forwarding": {
        "selected": "channels",
        "expanded": False,  # toggle open/close
        "channels": {"penalty":"off","delete":False,"mute_secs":30*60,"warn_secs":30*60,"ban_secs":30*60},
        "groups":   {"penalty":"off","delete":False,"mute_secs":30*60,"warn_secs":30*60,"ban_secs":30*60},
        "users":    {"penalty":"off","delete":False,"mute_secs":30*60,"warn_secs":30*60,"ban_secs":30*60},
        "bots":     {"penalty":"off","delete":False,"mute_secs":30*60,"warn_secs":30*60,"ban_secs":30*60},
    },

    # Total links block submenu
    "total_links": {
        "penalty": "off",             # off|warn|kick|mute|ban
        "delete": True,
        "mute_secs": 30*60,
        "warn_secs": 30*60,
        "ban_secs":  30*60
    },

    # Quote submenu (same behavior style as Forwarding)
    "quote_block": {
        "selected": "channels",
        "expanded": False,
        "channels": {"penalty":"off","delete":False,"mute_secs":30*60,"warn_secs":30*60,"ban_secs":30*60},
        "groups":   {"penalty":"off","delete":False,"mute_secs":30*60,"warn_secs":30*60,"ban_secs":30*60},
        "users":    {"penalty":"off","delete":False,"mute_secs":30*60,"warn_secs":30*60,"ban_secs":30*60},
        "bots":     {"penalty":"off","delete":False,"mute_secs":30*60,"warn_secs":30*60,"ban_secs":30*60},
    }
}

def _ensure_defaults(gid: int):
    g = GROUP_SETTINGS[gid]
    cfg = g.get("antispam_cfg")
    changed = False
    if not isinstance(cfg, dict):
        cfg = DEFAULT_ANTISPAM.copy()
        changed = True
    else:
        for k, v in DEFAULT_ANTISPAM.items():
            if k not in cfg:
                cfg[k] = v; changed = True
        for sec in ("tg_links","forwarding","total_links","quote_block"):
            if sec not in cfg or not isinstance(cfg[sec], dict):
                cfg[sec] = DEFAULT_ANTISPAM[sec].copy(); changed = True
            else:
                for k, v in DEFAULT_ANTISPAM[sec].items():
                    if k not in cfg[sec]:
                        cfg[sec][k] = v; changed = True

    # migrate old forwarding booleans -> new per-scope dict
    fwd = cfg.get("forwarding", {})
    if isinstance(fwd.get("channels", None), bool):
        cfg["forwarding"] = {
            "selected": "channels",
            "expanded": False,
            "channels": {"penalty":"off","delete":fwd.get("channels", False),"mute_secs":30*60,"warn_secs":30*60,"ban_secs":30*60},
            "groups":   {"penalty":"off","delete":fwd.get("groups",   False),"mute_secs":30*60,"warn_secs":30*60,"ban_secs":30*60},
            "users":    {"penalty":"off","delete":fwd.get("users",    False),"mute_secs":30*60,"warn_secs":30*60,"ban_secs":30*60},
            "bots":     {"penalty":"off","delete":fwd.get("bots",     False),"mute_secs":30*60,"warn_secs":30*60,"ban_secs":30*60},
        }
        changed = True

    if changed:
        g2 = dict(g); g2["antispam_cfg"] = cfg
        GROUP_SETTINGS[gid] = g2

def _mutate(gid: int, fn):
    _ensure_defaults(gid)
    g = GROUP_SETTINGS[gid]
    cfg = dict(g["antispam_cfg"])
    fn(cfg)
    g2 = dict(g); g2["antispam_cfg"] = cfg
    GROUP_SETTINGS[gid] = g2
    return cfg

# ------------- Common helpers -------------
def _human_duration(seconds: int) -> str:
    if not seconds:
        return "Off"
    td = timedelta(seconds=int(seconds))
    days = td.days
    secs = td.seconds
    h = secs // 3600
    m = (secs % 3600) // 60
    s = secs % 60
    parts = []
    if days: parts.append(f"{days} day{'s' if days!=1 else ''}")
    if h: parts.append(f"{h} hour{'s' if h!=1 else ''}")
    if m: parts.append(f"{m} minute{'s' if m!=1 else ''}")
    if s and not parts: parts.append(f"{s} second{'s' if s!=1 else ''}")
    return " ".join(parts) if parts else "0 seconds"

_UNIT_MAP = {
    "s":"seconds","sec":"seconds","secs":"seconds","second":"seconds","seconds":"seconds",
    "m":"minutes","min":"minutes","mins":"minutes","minute":"minutes","minutes":"minutes",
    "h":"hours","hr":"hours","hrs":"hours","hour":"hours","hours":"hours",
    "d":"days","day":"days","days":"days",
    "month":"months","months":"months",
    "y":"years","yr":"years","yrs":"years","year":"years","years":"years"
}
def _parse_duration_to_seconds(text: str) -> Optional[int]:
    text = (text or "").strip().lower()
    if not text:
        return None
    tokens = re.findall(r"(\d+)\s*([a-zA-Z]+)", text)
    if not tokens:
        return None
    total = 0
    for num, unit in tokens:
        unit = _UNIT_MAP.get(unit, unit)
        n = int(num)
        if unit == "seconds": total += n
        elif unit == "minutes": total += n*60
        elif unit == "hours": total += n*3600
        elif unit == "days": total += n*86400
        elif unit == "months": total += n*30*86400
        elif unit == "years": total += n*365*86400
        else:
            return None
    if total < 30: total = 30
    if total > 365*86400: total = 365*86400
    return total

# ------------- Main screen -------------
def _main_text() -> str:
    return (
        "🛡 <b>Anti-Spam</b>\n\n"
        "In this menu you can decide whether to protect your groups "
        "from unnecessary links, forwards, and quotes."
    )

def _main_kb(gid: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton("📘 Telegram links", callback_data=f"as:tg:{gid}"))
    kb.add(
        InlineKeyboardButton("✉️ Forwarding", callback_data=f"as:fwd:{gid}"),
        InlineKeyboardButton("💬 Quote",      callback_data=f"as:quote:{gid}")
    )
    kb.add(InlineKeyboardButton("🔗 Total links block", callback_data=f"as:all:{gid}"))
    kb.add(InlineKeyboardButton("🔙 Back", callback_data=f"open:{gid}"))
    return kb

# ------------- Telegram links submenu -------------
def _tg_text(gid: int) -> str:
    cfg = GROUP_SETTINGS[gid]["antispam_cfg"]["tg_links"]
    pen = cfg["penalty"].capitalize()
    deltxt = "Yes ✅" if cfg["delete"] else "No ✖️"
    base = (
        "📘 <b>Telegram links</b>\n"
        "From this menu you can set a punishment for users who send messages that contain Telegram links.\n\n"
        "🎯 <b>Username Antispam</b>: this option triggers the antispam when a <b>username</b> considered spam is sent.\n"
        "🤖 <b>Bots Antispam</b>: this option triggers the antispam when a <b>Bot link</b> is sent.\n\n"
        f"<b>Penalty:</b> {pen}"
    )
    if cfg["penalty"] == "mute":
        base += f" { _human_duration(cfg.get('mute_secs',1800)) }"
    elif cfg["penalty"] == "warn":
        base += f" { _human_duration(cfg.get('warn_secs',1800)) }"
    elif cfg["penalty"] == "ban":
        base += f" { _human_duration(cfg.get('ban_secs',1800)) }"
    base += f"\n<b>Deletion:</b> {deltxt}"
    return base

def _tg_kb(gid: int) -> InlineKeyboardMarkup:
    sec = GROUP_SETTINGS[gid]["antispam_cfg"]["tg_links"]
    kb = InlineKeyboardMarkup(row_width=3)
    kb.add(
        InlineKeyboardButton("✖️ Off",  callback_data=f"as:tg:pen:{gid}:off"),
        InlineKeyboardButton("❗ Warn", callback_data=f"as:tg:pen:{gid}:warn"),
        InlineKeyboardButton("❗ Kick", callback_data=f"as:tg:pen:{gid}:kick"),
    )
    kb.add(
        InlineKeyboardButton("🔇 Mute", callback_data=f"as:tg:pen:{gid}:mute"),
        InlineKeyboardButton("🚷 Ban",  callback_data=f"as:tg:pen:{gid}:ban"),
    )

    if sec["penalty"] == "mute":
        kb.add(InlineKeyboardButton("🔇 ⏱ Set mute duration", callback_data=f"as:tg:dur:{gid}:mute"))
    elif sec["penalty"] == "warn":
        kb.add(InlineKeyboardButton("❗ ⏱ Set warn duration", callback_data=f"as:tg:dur:{gid}:warn"))
    elif sec["penalty"] == "ban":
        kb.add(InlineKeyboardButton("🚷 ⏱ Set ban duration",  callback_data=f"as:tg:dur:{gid}:ban"))

    kb.add(InlineKeyboardButton(f"🗑 Delete Messages {'✅' if sec['delete'] else '✖️'}",
                                callback_data=f"as:tg:del:{gid}"))
    kb.add(InlineKeyboardButton(f"🎯 Username Antispam {'✅' if sec['username_antispam'] else '✖️'}",
                                callback_data=f"as:tg:uname:{gid}"))
    kb.add(InlineKeyboardButton(f"🤖 Bots Antispam {'✅' if sec['bots_antispam'] else '✖️'}",
                                callback_data=f"as:tg:bots:{gid}"))
    kb.add(InlineKeyboardButton("🔙 Back", callback_data=f"as:back:{gid}"),
           InlineKeyboardButton("🌞 Exceptions", callback_data=f"as:noop:{gid}"))
    return kb

def _tg_dur_prompt(gid: int, which: str) -> Tuple[str, InlineKeyboardMarkup]:
    sec = GROUP_SETTINGS[gid]["antispam_cfg"]["tg_links"]
    cur = _human_duration(sec.get(f"{which}_secs", 1800))
    txt = (
        f"⏱ <b>Set {which} duration</b>\n\n"
        "<b>Minimum:</b> 30 seconds\n"
        "<b>Maximum:</b> 365 days\n\n"
        "Example of format: <code>3 months 2 days 12 hours 4 minutes 34 seconds</code>\n\n"
        f"<b>Current duration:</b> {cur}"
    )
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("0️⃣ Remove duration", callback_data=f"as:tg:durset:{gid}:{which}:0"))
    kb.add(InlineKeyboardButton("✖️ Cancel", callback_data=f"as:tg:durcancel:{gid}"))
    return txt, kb

# ------------- Forwarding submenu (kept final) -------------
def _pen_summary(sec: dict) -> str:
    p = sec.get("penalty", "off")
    if p == "off":  return "Off"
    if p == "kick": return "Kick"
    if p == "warn": return "Warn " + _human_duration(sec.get("warn_secs", 1800))
    if p == "mute": return "Mute " + _human_duration(sec.get("mute_secs", 1800))
    if p == "ban":  return "Ban "  + _human_duration(sec.get("ban_secs", 1800))
    return "Off"

def _fwd_text(gid: int) -> str:
    fwd = GROUP_SETTINGS[gid]["antispam_cfg"]["forwarding"]

    def row(title: str, key: str) -> str:
        sec = fwd[key]
        line = _pen_summary(sec)
        if sec.get("delete"):
            line += "  + Deletion"
        return f"{title}\n└ {line}"

    return (
        "✉️ <b>Forwarding</b>\n"
        "Select punishment for users who forward messages in the group.\n\n"
        "Forward from groups option blocks messages written by an anonymous administrator "
        "of another group and forwarded to this group.\n\n"
        + "\n".join([
            row("📣 <b>Forwards from channels</b>", "channels"),
            row("👥 <b>Groups</b>", "groups"),
            row("👤 <b>Users</b>", "users"),
            row("🤖 <b>Bots</b>", "bots"),
        ])
    )

def _fwd_kb(gid: int) -> InlineKeyboardMarkup:
    fwd = GROUP_SETTINGS[gid]["antispam_cfg"]["forwarding"]
    sel = fwd.get("selected", "channels")
    expanded = fwd.get("expanded", False)
    sec = fwd[sel]

    def mark(lbl, on): return f"» {lbl} «" if on else lbl

    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton(mark("📣 Channels", sel == "channels"), callback_data=f"as:fwd:sel:{gid}:channels"),
        InlineKeyboardButton(mark("👥 Groups",   sel == "groups"),   callback_data=f"as:fwd:sel:{gid}:groups"),
    )
    kb.add(
        InlineKeyboardButton(mark("👤 Users",    sel == "users"),    callback_data=f"as:fwd:sel:{gid}:users"),
        InlineKeyboardButton(mark("🤖 Bots",     sel == "bots"),     callback_data=f"as:fwd:sel:{gid}:bots"),
    )

    if not expanded:
        kb.add(
            InlineKeyboardButton("🔙 Back", callback_data=f"as:back:{gid}"),
            InlineKeyboardButton("🌞 Exceptions", callback_data=f"as:noop:{gid}")
        )
        return kb

    kb.add(InlineKeyboardButton("────────────", callback_data=f"as:noop:{gid}"))
    kb.add(
        InlineKeyboardButton("✖️ Off",  callback_data=f"as:fwd:pen:{gid}:{sel}:off"),
        InlineKeyboardButton("❗ Warn", callback_data=f"as:fwd:pen:{gid}:{sel}:warn"),
        InlineKeyboardButton("❗ Kick", callback_data=f"as:fwd:pen:{gid}:{sel}:kick"),
    )
    kb.add(
        InlineKeyboardButton("🔇 Mute", callback_data=f"as:fwd:pen:{gid}:{sel}:mute"),
        InlineKeyboardButton("🚷 Ban",  callback_data=f"as:fwd:pen:{gid}:{sel}:ban"),
    )

    if sec["penalty"] == "mute":
        kb.add(InlineKeyboardButton("🔇 ⏱ Set mute duration", callback_data=f"as:fwd:dur:{gid}:{sel}:mute"))
    elif sec["penalty"] == "warn":
        kb.add(InlineKeyboardButton("❗ ⏱ Set warn duration", callback_data=f"as:fwd:dur:{gid}:{sel}:warn"))
    elif sec["penalty"] == "ban":
        kb.add(InlineKeyboardButton("🚷 ⏱ Set ban duration",  callback_data=f"as:fwd:dur:{gid}:{sel}:ban"))

    kb.add(
        InlineKeyboardButton(
            f"🗑 Delete Messages {'✅' if sec['delete'] else '✖️'}",
            callback_data=f"as:fwd:del:{gid}:{sel}"
        )
    )
    kb.add(
        InlineKeyboardButton("🔙 Back", callback_data=f"as:back:{gid}"),
        InlineKeyboardButton("🌞 Exceptions", callback_data=f"as:noop:{gid}")
    )
    return kb

def _fwd_dur_prompt(gid: int, which: str, kind: str) -> Tuple[str, InlineKeyboardMarkup]:
    sec = GROUP_SETTINGS[gid]["antispam_cfg"]["forwarding"][which]
    cur = _human_duration(sec.get(f"{kind}_secs", 1800))
    txt = (
        f"⏱ <b>Set {kind} duration</b>\n\n"
        "<b>Minimum:</b> 30 seconds\n"
        "<b>Maximum:</b> 365 days\n\n"
        "Example of format: <code>3 months 2 days 12 hours 4 minutes 34 seconds</code>\n\n"
        f"<b>Current duration:</b> {cur}"
    )
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("0️⃣ Remove duration", callback_data=f"as:fwd:durset:{gid}:{which}:{kind}:0"))
    kb.add(InlineKeyboardButton("✖️ Cancel", callback_data=f"as:fwd:durcancel:{gid}"))
    return txt, kb

# ------------- Quote submenu (same UX as Forwarding) -------------
def _quote_text(gid: int) -> str:
    qt = GROUP_SETTINGS[gid]["antispam_cfg"]["quote_block"]

    def row(title: str, key: str) -> str:
        sec = qt[key]
        line = _pen_summary(sec)
        if sec.get("delete"):
            line += "  + Deletion"
        return f"{title}\n└ {line}"

    return (
        "💬 <b>Quote</b>\n"
        "Select punishment for users who send messages containing quotes from external chats.\n\n"
        + "\n".join([
            row("📣 <b>Channels</b>", "channels"),
            row("👥 <b>Groups</b>", "groups"),
            row("👤 <b>Users</b>", "users"),
            row("🤖 <b>Bots</b>", "bots"),
        ])
    )

def _quote_kb(gid: int) -> InlineKeyboardMarkup:
    qt = GROUP_SETTINGS[gid]["antispam_cfg"]["quote_block"]
    sel = qt.get("selected", "channels")
    expanded = qt.get("expanded", False)
    sec = qt[sel]

    def mark(lbl, on): return f"» {lbl} «" if on else lbl

    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton(mark("📣 Channels", sel == "channels"), callback_data=f"as:quote:sel:{gid}:channels"),
        InlineKeyboardButton(mark("👥 Groups",   sel == "groups"),   callback_data=f"as:quote:sel:{gid}:groups"),
    )
    kb.add(
        InlineKeyboardButton(mark("👤 Users",    sel == "users"),    callback_data=f"as:quote:sel:{gid}:users"),
        InlineKeyboardButton(mark("🤖 Bots",     sel == "bots"),     callback_data=f"as:quote:sel:{gid}:bots"),
    )

    if not expanded:
        kb.add(
            InlineKeyboardButton("🔙 Back", callback_data=f"as:back:{gid}"),
            InlineKeyboardButton("🌞 Exceptions", callback_data=f"as:noop:{gid}")
        )
        return kb

    kb.add(InlineKeyboardButton("➖➖➖➖➖➖➖➖➖➖", callback_data=f"as:noop:{gid}"))
    kb.add(
        InlineKeyboardButton("✖️ Off",  callback_data=f"as:quote:pen:{gid}:{sel}:off"),
        InlineKeyboardButton("❗ Warn", callback_data=f"as:quote:pen:{gid}:{sel}:warn"),
        InlineKeyboardButton("❗ Kick", callback_data=f"as:quote:pen:{gid}:{sel}:kick"),
    )
    kb.add(
        InlineKeyboardButton("🔇 Mute", callback_data=f"as:quote:pen:{gid}:{sel}:mute"),
        InlineKeyboardButton("🚷 Ban",  callback_data=f"as:quote:pen:{gid}:{sel}:ban"),
    )

    if sec["penalty"] == "mute":
        kb.add(InlineKeyboardButton("🔇 ⏱ Set mute duration", callback_data=f"as:quote:dur:{gid}:{sel}:mute"))
    elif sec["penalty"] == "warn":
        kb.add(InlineKeyboardButton("❗ ⏱ Set warn duration", callback_data=f"as:quote:dur:{gid}:{sel}:warn"))
    elif sec["penalty"] == "ban":
        kb.add(InlineKeyboardButton("🚷 ⏱ Set ban duration",  callback_data=f"as:quote:dur:{gid}:{sel}:ban"))

    kb.add(
        InlineKeyboardButton(
            f"🗑 Delete Messages {'✅' if sec['delete'] else '✖️'}",
            callback_data=f"as:quote:del:{gid}:{sel}"
        )
    )
    kb.add(
        InlineKeyboardButton("🔙 Back", callback_data=f"as:back:{gid}"),
        InlineKeyboardButton("🌞 Exceptions", callback_data=f"as:noop:{gid}")
    )
    return kb

def _quote_dur_prompt(gid: int, which: str, kind: str) -> Tuple[str, InlineKeyboardMarkup]:
    sec = GROUP_SETTINGS[gid]["antispam_cfg"]["quote_block"][which]
    cur = _human_duration(sec.get(f"{kind}_secs", 1800))
    txt = (
        f"⏱ <b>Set {kind} duration</b>\n\n"
        "<b>Minimum:</b> 30 seconds\n"
        "<b>Maximum:</b> 365 days\n\n"
        "Example of format: <code>3 months 2 days 12 hours 4 minutes 34 seconds</code>\n\n"
        f"<b>Current duration:</b> {cur}"
    )
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("0️⃣ Remove duration", callback_data=f"as:quote:durset:{gid}:{which}:{kind}:0"))
    kb.add(InlineKeyboardButton("✖️ Cancel", callback_data=f"as:quote:durcancel:{gid}"))
    return txt, kb

# ------------- Total links block submenu -------------
def _all_text(gid: int) -> str:
    sec = GROUP_SETTINGS[gid]["antispam_cfg"]["total_links"]
    pen = sec["penalty"].capitalize()
    deltxt = "Yes ✅" if sec["delete"] else "No ✖️"

    dur = ""
    if sec["penalty"] == "mute":
        dur = _human_duration(sec.get("mute_secs", 1800))
    elif sec["penalty"] == "warn":
        dur = _human_duration(sec.get("warn_secs", 1800))
    elif sec["penalty"] == "ban":
        dur = _human_duration(sec.get("ban_secs", 1800))

    text = (
        "🔗 <b>TOTAL LINKS BLOCK</b>\n"
        "Choose the punishment for those who sends any kind of link.\n\n"
        f"<b>Penalty:</b> {pen}"
    )
    if dur:
        text += f" {dur}"
    text += f"\n<b>Deletion:</b> {deltxt}"
    return text

def _all_kb(gid: int) -> InlineKeyboardMarkup:
    sec = GROUP_SETTINGS[gid]["antispam_cfg"]["total_links"]
    kb = InlineKeyboardMarkup(row_width=3)
    kb.add(
        InlineKeyboardButton("✖️ Off",  callback_data=f"as:all:pen:{gid}:off"),
        InlineKeyboardButton("❗ Warn", callback_data=f"as:all:pen:{gid}:warn"),
        InlineKeyboardButton("❗ Kick", callback_data=f"as:all:pen:{gid}:kick"),
    )
    kb.add(
        InlineKeyboardButton("🔇 Mute", callback_data=f"as:all:pen:{gid}:mute"),
        InlineKeyboardButton("🚷 Ban",  callback_data=f"as:all:pen:{gid}:ban"),
    )

    if sec["penalty"] == "mute":
        kb.add(InlineKeyboardButton("🔇 ⏱ Set mute duration", callback_data=f"as:all:dur:{gid}:mute"))
    elif sec["penalty"] == "warn":
        kb.add(InlineKeyboardButton("❗ ⏱ Set warn duration", callback_data=f"as:all:dur:{gid}:warn"))
    elif sec["penalty"] == "ban":
        kb.add(InlineKeyboardButton("🚷 ⏱ Set ban duration",  callback_data=f"as:all:dur:{gid}:ban"))

    kb.add(InlineKeyboardButton(f"🗑 Delete Messages {'✅' if sec['delete'] else '✖️'}",
                                callback_data=f"as:all:del:{gid}"))
    kb.add(InlineKeyboardButton("🔙 Back", callback_data=f"as:back:{gid}"),
           InlineKeyboardButton("🌞 Exceptions", callback_data=f"as:noop:{gid}"))
    return kb

def _all_dur_prompt(gid: int, which: str) -> Tuple[str, InlineKeyboardMarkup]:
    sec = GROUP_SETTINGS[gid]["antispam_cfg"]["total_links"]
    cur = _human_duration(sec.get(f"{which}_secs", 1800))
    txt = (
        f"⏱ <b>Set {which} duration</b>\n\n"
        "<b>Minimum:</b> 30 seconds\n"
        "<b>Maximum:</b> 365 days\n\n"
        "Example of format: <code>3 months 2 days 12 hours 4 minutes 34 seconds</code>\n\n"
        f"<b>Current duration:</b> {cur}"
    )
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("0️⃣ Remove duration", callback_data=f"as:all:durset:{gid}:{which}:0"))
    kb.add(InlineKeyboardButton("✖️ Cancel", callback_data=f"as:all:durcancel:{gid}"))
    return txt, kb

# ------------- Register hooks -------------
def register(bot):
    # main open
    @bot.callback_query_handler(func=lambda c: c.data.startswith("menu:antispam:"))
    def open_main(c):
        gid = int(c.data.split(":")[2])
        if not is_user_admin(bot, gid, c.from_user.id):
            bot.answer_callback_query(c.id, "Not admin."); return
        _ensure_defaults(gid)
        _safe_edit_text(bot, _main_text(), c.message.chat.id, c.message.message_id, reply_markup=_main_kb(gid))

    # back to main
    @bot.callback_query_handler(func=lambda c: c.data.startswith("as:back:"))
    def back_main(c):
        gid = int(c.data.split(":")[2])
        _safe_edit_text(bot, _main_text(), c.message.chat.id, c.message.message_id, reply_markup=_main_kb(gid))

    # -------- Telegram links --------
    @bot.callback_query_handler(func=lambda c: c.data.startswith("as:tg:") and c.data.split(":")[2] not in ("del","uname","bots","pen","dur","durset","durcancel","ret"))
    def tg_open(c):
        gid = int(c.data.split(":")[2])
        _ensure_defaults(gid)
        _safe_edit_text(bot, _tg_text(gid), c.message.chat.id, c.message.message_id, reply_markup=_tg_kb(gid))

    @bot.callback_query_handler(func=lambda c: c.data.startswith("as:tg:pen:"))
    def tg_pen_set(c):
        _, _, _, gid, val = c.data.split(":"); gid = int(gid)
        if val not in ("off","warn","kick","mute","ban"): bot.answer_callback_query(c.id); return
        _mutate(gid, lambda cfg: cfg["tg_links"].__setitem__("penalty", val))
        _safe_edit_text(bot, _tg_text(gid), c.message.chat.id, c.message.message_id, reply_markup=_tg_kb(gid))
        bot.answer_callback_query(c.id, "Penalty set")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("as:tg:del:"))
    def tg_del_toggle(c):
        _, _, _, gid = c.data.split(":"); gid = int(gid)
        _mutate(gid, lambda cfg: cfg["tg_links"].__setitem__("delete", not cfg["tg_links"]["delete"]))
        _safe_edit_text(bot, _tg_text(gid), c.message.chat.id, c.message.message_id, reply_markup=_tg_kb(gid))
        bot.answer_callback_query(c.id, "Updated")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("as:tg:uname:"))
    def tg_uname_toggle(c):
        _, _, _, gid = c.data.split(":"); gid = int(gid)
        _mutate(gid, lambda cfg: cfg["tg_links"].__setitem__("username_antispam",
                                                             not cfg["tg_links"]["username_antispam"]))
        _safe_edit_text(bot, _tg_text(gid), c.message.chat.id, c.message.message_id, reply_markup=_tg_kb(gid))
        bot.answer_callback_query(c.id, "Updated")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("as:tg:bots:"))
    def tg_bots_toggle(c):
        _, _, _, gid = c.data.split(":"); gid = int(gid)
        _mutate(gid, lambda cfg: cfg["tg_links"].__setitem__("bots_antispam",
                                                             not cfg["tg_links"]["bots_antispam"]))
        _safe_edit_text(bot, _tg_text(gid), c.message.chat.id, c.message.message_id, reply_markup=_tg_kb(gid))
        bot.answer_callback_query(c.id, "Updated")

    # TG duration prompt
    @bot.callback_query_handler(func=lambda c: c.data.startswith("as:tg:dur:"))
    def tg_dur_prompt(c):
        _, _, _, gid, which = c.data.split(":"); gid = int(gid)
        if which not in ("mute","warn","ban"): bot.answer_callback_query(c.id); return
        txt, kb = _tg_dur_prompt(gid, which)
        PENDING_INPUT[c.from_user.id] = {"await":"as_tg_dur", "gid":gid, "which":which,
                                         "reply_to":(c.message.chat.id, c.message.message_id)}
        _safe_edit_text(bot, txt, c.message.chat.id, c.message.message_id, reply_markup=kb, parse_mode="HTML")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("as:tg:durset:"))
    def tg_dur_zero(c):
        _, _, _, gid, which, val = c.data.split(":"); gid = int(gid)
        if which not in ("mute","warn","ban") or val != "0": bot.answer_callback_query(c.id); return
        _mutate(gid, lambda cfg: cfg["tg_links"].__setitem__(f"{which}_secs", 0))
        _safe_edit_text(bot, _tg_text(gid), c.message.chat.id, c.message.message_id, reply_markup=_tg_kb(gid))
        bot.answer_callback_query(c.id, "Removed")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("as:tg:durcancel:"))
    def tg_dur_cancel(c):
        gid = int(c.data.split(":")[3])
        _safe_edit_text(bot, _tg_text(gid), c.message.chat.id, c.message.message_id, reply_markup=_tg_kb(gid))

    # TG duration input -> delete prompt → confirmation → Back
    @bot.message_handler(func=lambda m: PENDING_INPUT.get(m.from_user.id, {}).get("await") == "as_tg_dur")
    def tg_duration_input(m):
        ctx = PENDING_INPUT.pop(m.from_user.id)
        gid, which = ctx["gid"], ctx["which"]
        secs = _parse_duration_to_seconds(m.text or "")
        if secs is None:
            bot.reply_to(m, "✖️ Invalid duration. Example: <code>30 minutes</code> / <code>2 hours</code>", parse_mode="HTML")
            return
        _mutate(gid, lambda cfg: cfg["tg_links"].__setitem__(f"{which}_secs", int(secs)))

        chat_id, msg_id = ctx["reply_to"]
        try: bot.delete_message(chat_id, msg_id)
        except Exception: pass

        human = _human_duration(int(secs))
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(InlineKeyboardButton("🔙 Back", callback_data=f"as:tg:ret:{gid}"))
        bot.send_message(chat_id, f"✅ {which.capitalize()} duration set to: {human}", reply_markup=kb)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("as:tg:ret:"))
    def tg_back_after_set(c):
        gid = int(c.data.split(":")[3])
        _safe_edit_text(bot, _tg_text(gid), c.message.chat.id, c.message.message_id, reply_markup=_tg_kb(gid))

    # -------- Forwarding (final UI) --------
    @bot.callback_query_handler(func=lambda c: c.data.startswith("as:fwd:") and c.data.split(":")[2] not in ("sel","pen","del","dur","durset","durcancel"))
    def fwd_open(c):
        gid = int(c.data.split(":")[2])
        _ensure_defaults(gid)
        _safe_edit_text(bot, _fwd_text(gid), c.message.chat.id, c.message.message_id,
                        reply_markup=_fwd_kb(gid))

    @bot.callback_query_handler(func=lambda c: c.data.startswith("as:fwd:sel:"))
    def fwd_sel(c):
        _,_,_, gid, which = c.data.split(":"); gid = int(gid)
        if which not in ("channels","groups","users","bots"): bot.answer_callback_query(c.id); return
        def _toggle(cfg):
            fwd = cfg["forwarding"]
            if fwd.get("selected") == which:
                fwd["expanded"] = not fwd.get("expanded", False)  # toggle open/close
            else:
                fwd["selected"] = which
                fwd["expanded"] = True
        _mutate(gid, _toggle)
        _safe_edit_text(bot, _fwd_text(gid), c.message.chat.id, c.message.message_id,
                        reply_markup=_fwd_kb(gid))
        bot.answer_callback_query(c.id)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("as:fwd:pen:"))
    def fwd_pen(c):
        _,_,_, gid, which, pen = c.data.split(":"); gid = int(gid)
        if which not in ("channels","groups","users","bots"): bot.answer_callback_query(c.id); return
        if pen not in ("off","warn","kick","mute","ban"): bot.answer_callback_query(c.id); return
        def _set(cfg):
            cfg["forwarding"][which]["penalty"] = pen
            cfg["forwarding"]["selected"] = which
            cfg["forwarding"]["expanded"] = True
        _mutate(gid, _set)
        _safe_edit_text(bot, _fwd_text(gid), c.message.chat.id, c.message.message_id,
                        reply_markup=_fwd_kb(gid))
        bot.answer_callback_query(c.id, "Penalty set")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("as:fwd:del:"))
    def fwd_del(c):
        _,_,_, gid, which = c.data.split(":"); gid = int(gid)
        def _flip(cfg):
            cur = cfg["forwarding"][which]["delete"]
            cfg["forwarding"][which]["delete"] = not cur
            cfg["forwarding"]["selected"] = which
            cfg["forwarding"]["expanded"] = True
        _mutate(gid, _flip)
        _safe_edit_text(bot, _fwd_text(gid), c.message.chat.id, c.message.message_id,
                        reply_markup=_fwd_kb(gid))
        bot.answer_callback_query(c.id, "Updated")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("as:fwd:dur:"))
    def fwd_dur_prompt_cb(c):
        _,_,_, gid, which, kind = c.data.split(":"); gid = int(gid)
        if which not in ("channels","groups","users","bots"): bot.answer_callback_query(c.id); return
        if kind  not in ("mute","warn","ban"): bot.answer_callback_query(c.id); return
        txt, kb = _fwd_dur_prompt(gid, which, kind)
        PENDING_INPUT[c.from_user.id] = {"await":"as_fwd_dur","gid":gid,"which":which,"kind":kind,
                                         "reply_to":(c.message.chat.id, c.message.message_id)}
        _safe_edit_text(bot, txt, c.message.chat.id, c.message.message_id, reply_markup=kb, parse_mode="HTML")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("as:fwd:durset:"))
    def fwd_dur_zero(c):
        _,_,_, gid, which, kind, val = c.data.split(":"); gid = int(gid)
        if val != "0": bot.answer_callback_query(c.id); return
        def _set0(cfg):
            cfg["forwarding"][which][f"{kind}_secs"] = 0
            cfg["forwarding"]["selected"] = which
            cfg["forwarding"]["expanded"] = True
        _mutate(gid, _set0)
        _safe_edit_text(bot, _fwd_text(gid), c.message.chat.id, c.message.message_id,
                        reply_markup=_fwd_kb(gid))
        bot.answer_callback_query(c.id, "Removed")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("as:fwd:durcancel:"))
    def fwd_dur_cancel(c):
        gid = int(c.data.split(":")[3])
        _mutate(gid, lambda cfg: cfg["forwarding"].__setitem__("expanded", True))
        _safe_edit_text(bot, _fwd_text(gid), c.message.chat.id, c.message.message_id,
                        reply_markup=_fwd_kb(gid))

    @bot.message_handler(func=lambda m: PENDING_INPUT.get(m.from_user.id, {}).get("await") == "as_fwd_dur")
    def fwd_duration_input(m):
        ctx = PENDING_INPUT.pop(m.from_user.id)
        gid, which, kind = ctx["gid"], ctx["which"], ctx["kind"]
        secs = _parse_duration_to_seconds(m.text or "")
        if secs is None:
            bot.reply_to(m, "✖️ Invalid duration. Example: <code>30 minutes</code>", parse_mode="HTML")
            return
        def _apply(cfg):
            cfg["forwarding"][which][f"{kind}_secs"] = int(secs)
            cfg["forwarding"]["selected"] = which
            cfg["forwarding"]["expanded"] = True
        _mutate(gid, _apply)
        chat_id, msg_id = ctx["reply_to"]
        try: bot.delete_message(chat_id, msg_id)
        except Exception: pass
        human = _human_duration(int(secs))
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(InlineKeyboardButton("🔙 Back", callback_data=f"as:fwd:sel:{gid}:{which}"))
        bot.send_message(chat_id, f"✅ {kind.capitalize()} duration set to: {human}", reply_markup=kb)

    # -------- Total links block --------
    @bot.callback_query_handler(func=lambda c: c.data.startswith("as:all:") and c.data.split(":")[2] not in ("pen","del","dur","durset","durcancel","ret"))
    def all_open(c):
        gid = int(c.data.split(":")[2])
        _ensure_defaults(gid)
        _safe_edit_text(bot, _all_text(gid), c.message.chat.id, c.message.message_id, reply_markup=_all_kb(gid))

    @bot.callback_query_handler(func=lambda c: c.data.startswith("as:all:pen:"))
    def all_pen_set(c):
        _, _, _, gid, val = c.data.split(":"); gid = int(gid)
        if val not in ("off","warn","kick","mute","ban"): bot.answer_callback_query(c.id); return
        _mutate(gid, lambda cfg: cfg["total_links"].__setitem__("penalty", val))
        _safe_edit_text(bot, _all_text(gid), c.message.chat.id, c.message.message_id, reply_markup=_all_kb(gid))
        bot.answer_callback_query(c.id, "Penalty set")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("as:all:del:"))
    def all_del_toggle(c):
        _, _, _, gid = c.data.split(":"); gid = int(gid)
        _mutate(gid, lambda cfg: cfg["total_links"].__setitem__("delete", not cfg["total_links"]["delete"]))
        _safe_edit_text(bot, _all_text(gid), c.message.chat.id, c.message.message_id, reply_markup=_all_kb(gid))
        bot.answer_callback_query(c.id, "Updated")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("as:all:dur:"))
    def all_dur_prompt(c):
        _, _, _, gid, which = c.data.split(":"); gid = int(gid)
        if which not in ("mute","warn","ban"): bot.answer_callback_query(c.id); return
        txt, kb = _all_dur_prompt(gid, which)
        PENDING_INPUT[c.from_user.id] = {"await":"as_all_dur", "gid":gid, "which":which,
                                         "reply_to":(c.message.chat.id, c.message.message_id)}
        _safe_edit_text(bot, txt, c.message.chat.id, c.message.message_id, reply_markup=kb, parse_mode="HTML")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("as:all:durset:"))
    def all_dur_set_zero(c):
        _, _, _, gid, which, val = c.data.split(":"); gid = int(gid)
        if which not in ("mute","warn","ban") or val != "0": bot.answer_callback_query(c.id); return
        _mutate(gid, lambda cfg: cfg["total_links"].__setitem__(f"{which}_secs", 0))
        _safe_edit_text(bot, _all_text(gid), c.message.chat.id, c.message.message_id, reply_markup=_all_kb(gid))
        bot.answer_callback_query(c.id, "Removed")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("as:all:durcancel:"))
    def all_dur_cancel(c):
        gid = int(c.data.split(":")[3])
        _safe_edit_text(bot, _all_text(gid), c.message.chat.id, c.message.message_id, reply_markup=_all_kb(gid))

    @bot.message_handler(func=lambda m: PENDING_INPUT.get(m.from_user.id, {}).get("await") == "as_all_dur")
    def handle_all_duration_input(m):
        ctx = PENDING_INPUT.pop(m.from_user.id)
        gid, which = ctx["gid"], ctx["which"]
        secs = _parse_duration_to_seconds(m.text or "")
        if secs is None:
            bot.reply_to(m, "✖️ Invalid duration. Example: <code>30 minutes</code> / <code>2 hours</code>", parse_mode="HTML")
            return

        _mutate(gid, lambda cfg: cfg["total_links"].__setitem__(f"{which}_secs", int(secs)))

        chat_id, msg_id = ctx["reply_to"]
        try: bot.delete_message(chat_id, msg_id)
        except Exception: pass

        human = _human_duration(int(secs))
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(InlineKeyboardButton("🔙 Back", callback_data=f"as:all:ret:{gid}"))
        bot.send_message(chat_id, f"✅ Duration set to: {human}", reply_markup=kb)

    # -------- Quote (new UI like Forwarding) --------
    @bot.callback_query_handler(func=lambda c: c.data.startswith("as:quote:") and c.data.split(":")[2] not in ("sel","pen","del","dur","durset","durcancel"))
    def quote_open(c):
        gid = int(c.data.split(":")[2])
        _ensure_defaults(gid)
        _safe_edit_text(bot, _quote_text(gid), c.message.chat.id, c.message.message_id,
                        reply_markup=_quote_kb(gid))

    @bot.callback_query_handler(func=lambda c: c.data.startswith("as:quote:sel:"))
    def quote_sel(c):
        _,_,_, gid, which = c.data.split(":"); gid = int(gid)
        if which not in ("channels","groups","users","bots"): bot.answer_callback_query(c.id); return
        def _toggle(cfg):
            qt = cfg["quote_block"]
            if qt.get("selected") == which:
                qt["expanded"] = not qt.get("expanded", False)
            else:
                qt["selected"] = which
                qt["expanded"] = True
        _mutate(gid, _toggle)
        _safe_edit_text(bot, _quote_text(gid), c.message.chat.id, c.message.message_id,
                        reply_markup=_quote_kb(gid))
        bot.answer_callback_query(c.id)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("as:quote:pen:"))
    def quote_pen(c):
        _,_,_, gid, which, pen = c.data.split(":"); gid = int(gid)
        if which not in ("channels","groups","users","bots"): bot.answer_callback_query(c.id); return
        if pen not in ("off","warn","kick","mute","ban"): bot.answer_callback_query(c.id); return
        def _set(cfg):
            cfg["quote_block"][which]["penalty"] = pen
            cfg["quote_block"]["selected"] = which
            cfg["quote_block"]["expanded"] = True
        _mutate(gid, _set)
        _safe_edit_text(bot, _quote_text(gid), c.message.chat.id, c.message.message_id,
                        reply_markup=_quote_kb(gid))
        bot.answer_callback_query(c.id, "Penalty set")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("as:quote:del:"))
    def quote_del(c):
        _,_,_, gid, which = c.data.split(":"); gid = int(gid)
        def _flip(cfg):
            cur = cfg["quote_block"][which]["delete"]
            cfg["quote_block"][which]["delete"] = not cur
            cfg["quote_block"]["selected"] = which
            cfg["quote_block"]["expanded"] = True
        _mutate(gid, _flip)
        _safe_edit_text(bot, _quote_text(gid), c.message.chat.id, c.message.message_id,
                        reply_markup=_quote_kb(gid))
        bot.answer_callback_query(c.id, "Updated")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("as:quote:dur:"))
    def quote_dur_prompt_cb(c):
        _,_,_, gid, which, kind = c.data.split(":"); gid = int(gid)
        if which not in ("channels","groups","users","bots"): bot.answer_callback_query(c.id); return
        if kind  not in ("mute","warn","ban"): bot.answer_callback_query(c.id); return
        txt, kb = _quote_dur_prompt(gid, which, kind)
        PENDING_INPUT[c.from_user.id] = {"await":"as_quote_dur","gid":gid,"which":which,"kind":kind,
                                         "reply_to":(c.message.chat.id, c.message.message_id)}
        _safe_edit_text(bot, txt, c.message.chat.id, c.message.message_id, reply_markup=kb, parse_mode="HTML")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("as:quote:durset:"))
    def quote_dur_zero(c):
        _,_,_, gid, which, kind, val = c.data.split(":"); gid = int(gid)
        if val != "0": bot.answer_callback_query(c.id); return
        def _set0(cfg):
            cfg["quote_block"][which][f"{kind}_secs"] = 0
            cfg["quote_block"]["selected"] = which
            cfg["quote_block"]["expanded"] = True
        _mutate(gid, _set0)
        _safe_edit_text(bot, _quote_text(gid), c.message.chat.id, c.message.message_id,
                        reply_markup=_quote_kb(gid))
        bot.answer_callback_query(c.id, "Removed")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("as:quote:durcancel:"))
    def quote_dur_cancel(c):
        gid = int(c.data.split(":")[3])
        _mutate(gid, lambda cfg: cfg["quote_block"].__setitem__("expanded", True))
        _safe_edit_text(bot, _quote_text(gid), c.message.chat.id, c.message.message_id,
                        reply_markup=_quote_kb(gid))

    @bot.message_handler(func=lambda m: PENDING_INPUT.get(m.from_user.id, {}).get("await") == "as_quote_dur")
    def quote_duration_input(m):
        ctx = PENDING_INPUT.pop(m.from_user.id)
        gid, which, kind = ctx["gid"], ctx["which"], ctx["kind"]
        secs = _parse_duration_to_seconds(m.text or "")
        if secs is None:
            bot.reply_to(m, "✖️ Invalid duration. Example: <code>30 minutes</code>", parse_mode="HTML")
            return
        def _apply(cfg):
            cfg["quote_block"][which][f"{kind}_secs"] = int(secs)
            cfg["quote_block"]["selected"] = which
            cfg["quote_block"]["expanded"] = True
        _mutate(gid, _apply)
        chat_id, msg_id = ctx["reply_to"]
        try: bot.delete_message(chat_id, msg_id)
        except Exception: pass
        human = _human_duration(int(secs))
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(InlineKeyboardButton("🔙 Back", callback_data=f"as:quote:sel:{gid}:{which}"))
        bot.send_message(chat_id, f"✅ {kind.capitalize()} duration set to: {human}", reply_markup=kb)

