"""Making the browser look like another one: a phone, another country, a slow network.

One step, `emulate KIND VALUE`, carries all of it, and a trail keeps it like any other step:
a task learned on a phone layout, in Tokyo's time zone, replays on a phone layout in Tokyo's
time zone. Every kind is undone with `emulate KIND off`.

What Playwright can set on a running page, it sets here (`set_viewport_size`,
`emulate_media`, `set_offline`, `set_geolocation`). The rest Playwright only takes when a
context is made, and Dejo's context is a signed-in profile that cannot be remade, so it goes
through the Chrome DevTools Protocol, the way Chrome DevTools and Puppeteer do. A CDP session
belongs to one page, so `Browser` applies everything again to every tab that opens.

Nothing here hides that the browser is automated, or fakes anything to get past a site's
own checks. It changes what a person could change in their own browser's settings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from playwright.sync_api import BrowserContext, Page

# What `off` is written as, for every kind.
OFF = "off"

# Network speeds, in bytes a second and milliseconds of delay, as Chrome DevTools names them.
# The numbers are Puppeteer's `PredefinedNetworkConditions` (Apache-2.0, Copyright 2017
# Google Inc.), which Chrome DevTools MCP uses: values, not code, so a page that is slow in
# DevTools is equally slow here.
NETWORKS: dict[str, dict[str, float]] = {
    "slow3g": {"downloadThroughput": 50_000, "uploadThroughput": 50_000, "latency": 2_000},
    "fast3g": {"downloadThroughput": 180_000, "uploadThroughput": 84_375, "latency": 562.5},
    "slow4g": {"downloadThroughput": 180_000, "uploadThroughput": 84_375, "latency": 562.5},
    "fast4g": {"downloadThroughput": 1_012_500, "uploadThroughput": 168_750, "latency": 165},
}

# Chrome slows its CPU by a whole number from 1 (full speed) to 20, as DevTools allows.
MAX_CPU_SLOWDOWN = 20

COLOR_SCHEMES = frozenset({"dark", "light", "no-preference"})
MEDIA = frozenset({"screen", "print"})
MOTION = frozenset({"reduce", "no-preference"})


class EmulationError(ValueError):
    """An `emulate` line Dejo cannot carry out, said in words a person can act on."""


@dataclass(frozen=True)
class KindSpec:
    name: str
    summary: str
    example: str


KINDS: dict[str, KindSpec] = {
    spec.name: spec
    for spec in (
        KindSpec("viewport", "the window's size, in pixels", "emulate viewport 390x844"),
        KindSpec(
            "device",
            "a phone or tablet: its screen, its pixel density, touch and its user agent",
            'emulate device "iPhone 13"',
        ),
        KindSpec("timezone", "the time zone the page sees", "emulate timezone Asia/Tokyo"),
        KindSpec("locale", "the language and number format", "emulate locale de-DE"),
        KindSpec("color", "light or dark mode", "emulate color dark"),
        KindSpec("media", "how the page looks when printed", "emulate media print"),
        KindSpec("motion", "the setting that asks for less animation", "emulate motion reduce"),
        KindSpec("offline", "no network at all", "emulate offline on"),
        KindSpec(
            "network", "a slow network: slow3g, fast3g, slow4g, fast4g", "emulate network slow3g"
        ),
        KindSpec("cpu", "a slower computer, 2 to 20 times slower", "emulate cpu 4"),
        KindSpec("geolocation", "where the browser says it is", "emulate geolocation 18.52,73.85"),
    )
}


def catalogue() -> str:
    """Every kind, for the `help` reply."""
    return "\n".join(f"  {spec.example} — {spec.summary}" for spec in KINDS.values())


def parse(value: str) -> tuple[str, str]:
    """`timezone Asia/Tokyo` into its kind and its setting, or EmulationError."""
    kind, _, setting = value.strip().partition(" ")
    kind, setting = kind.lower(), setting.strip().strip('"')
    if kind not in KINDS:
        raise EmulationError(f"cannot emulate {kind!r}. Kinds: {', '.join(KINDS)}")
    if not setting:
        raise EmulationError(f"emulate {kind} needs a setting, like: {KINDS[kind].example}")
    return kind, setting


def apply(page: Page, context: BrowserContext, kind: str, setting: str, devices: Any) -> None:
    """Set one kind on one page (and, for what lives there, on the context)."""
    off = setting.lower() == OFF
    if kind == "viewport":
        _viewport(page, setting, off)
    elif kind == "device":
        _device(page, context, setting, off, devices)
    elif kind == "timezone":
        _cdp(page, context, "Emulation.setTimezoneOverride", {"timezoneId": "" if off else setting})
    elif kind == "locale":
        _locale(page, context, setting, off)
    elif kind in ("color", "media", "motion"):
        _media(page, kind, setting, off)
    elif kind == "offline":
        context.set_offline(not off and setting.lower() in ("on", "true", "yes"))
    elif kind == "network":
        _network(page, context, setting, off)
    elif kind == "cpu":
        _cpu(page, context, setting, off)
    else:
        _geolocation(context, setting, off)


def _viewport(page: Page, setting: str, off: bool) -> None:
    width, _, height = ("1280x720" if off else setting).lower().partition("x")
    if not (width.isdigit() and height.isdigit()):
        raise EmulationError(f"a viewport is WIDTHxHEIGHT, like 390x844, not {setting!r}")
    page.set_viewport_size({"width": int(width), "height": int(height)})


def _device(page: Page, context: BrowserContext, name: str, off: bool, devices: Any) -> None:
    if off:
        _cdp(page, context, "Emulation.clearDeviceMetricsOverride", {})
        _cdp(page, context, "Emulation.setTouchEmulationEnabled", {"enabled": False})
        _cdp(page, context, "Emulation.setUserAgentOverride", {"userAgent": ""})
        return
    found = devices.get(name)
    if found is None:
        near = [known for known in devices if name.lower() in known.lower()][:8]
        hint = f" Close names: {', '.join(near)}." if near else ""
        raise EmulationError(f"no device called {name!r}.{hint} Names are Playwright's own.")
    size = found["viewport"]
    page.set_viewport_size(size)
    _cdp(
        page,
        context,
        "Emulation.setDeviceMetricsOverride",
        {
            "width": size["width"],
            "height": size["height"],
            "deviceScaleFactor": found["device_scale_factor"],
            "mobile": found["is_mobile"],
        },
    )
    _cdp(page, context, "Emulation.setTouchEmulationEnabled", {"enabled": found["has_touch"]})
    _cdp(page, context, "Emulation.setUserAgentOverride", {"userAgent": found["user_agent"]})


def _locale(page: Page, context: BrowserContext, setting: str, off: bool) -> None:
    """The language of numbers and dates, and the one the page and the sites are told."""
    _cdp(page, context, "Emulation.setLocaleOverride", {} if off else {"locale": setting})
    agent = page.evaluate("() => navigator.userAgent")
    told = {"userAgent": agent} if off else {"userAgent": agent, "acceptLanguage": setting}
    _cdp(page, context, "Emulation.setUserAgentOverride", told)


def _media(page: Page, kind: str, setting: str, off: bool) -> None:
    allowed = {"color": COLOR_SCHEMES, "media": MEDIA, "motion": MOTION}[kind]
    if not off and setting not in allowed:
        raise EmulationError(f"emulate {kind} takes {', '.join(sorted(allowed))} or off")
    chosen = None if off else setting
    if kind == "color":
        page.emulate_media(color_scheme=chosen)  # type: ignore[arg-type]
    elif kind == "media":
        page.emulate_media(media=chosen)  # type: ignore[arg-type]
    else:
        page.emulate_media(reduced_motion=chosen)  # type: ignore[arg-type]


def _network(page: Page, context: BrowserContext, setting: str, off: bool) -> None:
    name = setting.lower().replace(" ", "")
    if off or name == "none":
        conditions = {
            "offline": False,
            "latency": 0,
            "downloadThroughput": -1,
            "uploadThroughput": -1,
        }
    elif name == "offline":
        conditions = {"offline": True, "latency": 0, "downloadThroughput": 0, "uploadThroughput": 0}
    elif name in NETWORKS:
        conditions = {"offline": False, **NETWORKS[name]}
    else:
        raise EmulationError(f"emulate network takes {', '.join(NETWORKS)}, offline or off")
    _cdp(page, context, "Network.enable", {})
    _cdp(page, context, "Network.emulateNetworkConditions", conditions)


def _cpu(page: Page, context: BrowserContext, setting: str, off: bool) -> None:
    rate = 1 if off else setting
    if not str(rate).isdigit() or not 1 <= int(rate) <= MAX_CPU_SLOWDOWN:
        raise EmulationError(f"emulate cpu takes a slowdown from 1 to {MAX_CPU_SLOWDOWN}")
    _cdp(page, context, "Emulation.setCPUThrottlingRate", {"rate": int(rate)})


def _geolocation(context: BrowserContext, setting: str, off: bool) -> None:
    if off:
        context.set_geolocation(None)
        return
    latitude, _, longitude = setting.replace(" ", "").partition(",")
    try:
        where = {"latitude": float(latitude), "longitude": float(longitude)}
    except ValueError:
        raise EmulationError(
            f"a place is LATITUDE,LONGITUDE, like 18.52,73.85: {setting!r}"
        ) from None
    # A position without the permission makes a site wait for a fix that never comes.
    context.grant_permissions(["geolocation"])
    context.set_geolocation(where)


def _cdp(page: Page, context: BrowserContext, method: str, params: dict[str, Any]) -> None:
    """One DevTools call on one page. The session is kept on the page, made once."""
    session = getattr(page, "_dejo_cdp", None)
    if session is None:
        session = context.new_cdp_session(page)
        page._dejo_cdp = session  # type: ignore[attr-defined]
    session.send(method, params)
