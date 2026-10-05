"""What the dashboard may publish: the same rules the Android app applies when it validates
the API's answers (core/data/.../ConfigValidator.kt). Publishing anything the app would drop
or reject is refused here, with the field that is wrong."""
from __future__ import annotations

import re
from typing import Annotated, Any, ClassVar, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError, model_validator

ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
HOST_RE = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,61}[a-z0-9]$")
SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]{0,31}$")
COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
IMAGE_RE = re.compile(r"^(logos|icons/categories)/[a-z0-9][a-z0-9._-]{0,100}\.png$")
FORBIDDEN_SCHEMES = {"http", "https", "javascript", "file", "content", "data", "blob", "about", "chrome", "wss", "ws"}


def _id(value: str) -> str:
    if not ID_RE.match(value):
        raise ValueError("lowercase letters, digits, '-' or '_' (start with a letter or digit, ≤ 64)")
    return value


def _https(value: str) -> str:
    value = value.strip()
    if not re.match(r"^https://[^/\s?#]+", value):
        raise ValueError("must be an https:// URL")
    return value


def _host(value: str) -> str:
    value = value.strip().lower().removeprefix("*.").rstrip(".")
    if not HOST_RE.match(value):
        raise ValueError(f"not a domain: {value!r}")
    return value


def _scheme(value: str) -> str:
    value = value.strip().lower().removesuffix("://").removesuffix(":")
    if not SCHEME_RE.match(value):
        raise ValueError(f"not a URI scheme: {value!r}")
    if value in FORBIDDEN_SCHEMES:
        raise ValueError(f"{value!r} can't be handed to another app")
    return value


def _color(value: str) -> str:
    if not COLOR_RE.match(value):
        raise ValueError("a color like #2F9E44")
    return value.upper()


def _image(value: str) -> str:
    if IMAGE_RE.match(value) or value.startswith("https://"):
        return value
    raise ValueError("an uploaded image (logos/… or icons/categories/…) or an https URL")


Id = Annotated[str, AfterValidator(_id)]
HttpsUrl = Annotated[str, AfterValidator(_https)]
Host = Annotated[str, AfterValidator(_host)]
Scheme = Annotated[str, AfterValidator(_scheme)]
Color = Annotated[str, AfterValidator(_color)]
ImageRef = Annotated[str, AfterValidator(_image)]


class Model(BaseModel):
    # Unknown fields are kept: the app may support fields this dashboard doesn't edit yet.
    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)


class Text(Model):
    """Localized text: Persian and/or English. A plain string counts as English."""

    MAX: ClassVar[int] = 64
    fa: str | None = None
    en: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _from_string(cls, value: Any) -> Any:
        return {"en": value} if isinstance(value, str) else value

    @model_validator(mode="after")
    def _check(self) -> "Text":
        values = {lang: text for lang, text in (self.model_dump(exclude_none=True)).items() if isinstance(text, str) and text}
        if not values:
            raise ValueError("enter Persian or English text")
        for lang, text in values.items():
            if len(text) > self.MAX:
                raise ValueError(f"{lang}: at most {self.MAX} characters")
        return self


class Title(Text):
    MAX = 64


class Description(Text):
    MAX = 240


class Message(Text):
    MAX = 400


class Badge(Text):
    MAX = 16


class Permissions(Model):
    location: bool = False
    camera: bool = False
    microphone: bool = False


class UserAgent(Model):
    mode: Literal["DEFAULT", "STRIP_WEBVIEW_MARKER", "CUSTOM"] = "DEFAULT"
    value: str | None = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def _custom_needs_value(self) -> "UserAgent":
        if self.mode == "CUSTOM" and not self.value:
            raise ValueError("a custom user agent needs a value")
        return self


class ErrorPage(Model):
    message: Message | None = None
    helpUrl: HttpsUrl | None = None


class WebRuntime(Model):
    allowedDomains: list[Host] = Field(default_factory=list)
    javascript: bool = True
    domStorage: bool = True
    permissions: Permissions = Field(default_factory=Permissions)
    fileUpload: bool = True
    downloads: bool = True
    popupPolicy: Literal["NEW_TAB", "SAME_TAB", "EXTERNAL_BROWSER", "BLOCK"] = "NEW_TAB"
    offDomainNavigation: Literal["STAY_IN_TAB", "OPEN_EXTERNALLY"] = "STAY_IN_TAB"
    externalDomains: list[Host] = Field(default_factory=list)
    externalSchemes: list[Scheme] = Field(default_factory=list)
    thirdPartyCookies: bool = True
    userAgent: UserAgent | None = None
    cacheMode: Literal["DEFAULT", "PREFER_CACHE", "NO_CACHE"] = "DEFAULT"
    keepAlive: Literal["LOW", "NORMAL", "HIGH"] = "NORMAL"
    restoreLastUrl: bool = True
    errorPage: ErrorPage | None = None


class Maintenance(Model):
    message: Message | None = None


class Service(Model):
    id: Id
    name: Title
    description: Description | None = None
    categoryId: Id
    url: HttpsUrl
    logo: ImageRef | None = None
    brandColor: Color | None = None
    enabled: bool = True
    order: int = Field(default=1000, ge=0)
    featured: bool = False
    badge: Badge | None = None
    compatibility: Literal["SUPPORTED", "PARTIAL", "EXPERIMENTAL", "DISABLED"] = "SUPPORTED"
    keywords: list[Annotated[str, Field(min_length=1, max_length=40)]] = Field(default_factory=list, max_length=30)
    maintenance: Maintenance | None = None
    web: WebRuntime = Field(default_factory=WebRuntime)


class Category(Model):
    id: Id
    title: Title
    icon: ImageRef | None = None
    color: Color | None = None
    order: int = Field(default=1000, ge=0)
    enabled: bool = True


class CompareGroup(Model):
    id: Id
    title: Title | None = None
    serviceIds: list[Id] = Field(min_length=2)


class WebDefaults(Model):
    paymentDomains: list[Host] = Field(default_factory=list)
    externalSchemes: list[Scheme] = Field(default_factory=list)


class Links(Model):
    privacyPolicyUrl: HttpsUrl | None = None
    supportUrl: HttpsUrl | None = None


class Catalog(Model):
    schemaVersion: Literal[1] = 1
    configVersion: str | None = Field(default=None, max_length=64)
    refreshIntervalSeconds: int = Field(default=3600, ge=300, le=7 * 24 * 3600)
    features: dict[str, bool] = Field(default_factory=dict)
    web: WebDefaults = Field(default_factory=WebDefaults)
    links: Links = Field(default_factory=Links)
    categories: list[Category] = Field(default_factory=list)
    services: list[Service] = Field(default_factory=list)
    compareGroups: list[CompareGroup] = Field(default_factory=list)

    @model_validator(mode="after")
    def _references(self) -> "Catalog":
        problems = []
        for kind, items in (("category", self.categories), ("service", self.services), ("compare group", self.compareGroups)):
            seen: set[str] = set()
            for item in items:
                if item.id in seen:
                    problems.append(f"duplicate {kind} id {item.id!r}")
                seen.add(item.id)
        category_ids = {c.id for c in self.categories}
        service_ids = {s.id for s in self.services}
        problems += [f"service {s.id!r}: unknown category {s.categoryId!r}" for s in self.services if s.categoryId not in category_ids]
        for group in self.compareGroups:
            unknown = [sid for sid in group.serviceIds if sid not in service_ids]
            if unknown:
                problems.append(f"compare group {group.id!r}: unknown services {unknown}")
        if not any(s.enabled for s in self.services):
            problems.append("at least one service must be enabled")
        if problems:
            raise ValueError("; ".join(problems))
        return self


class Rule(Model):
    minimumSupportedVersion: int | None = Field(default=None, ge=0)
    latestVersion: int | None = Field(default=None, ge=0)
    forceUpdate: bool | None = None
    updateUrl: HttpsUrl | None = None
    message: Message | None = None
    optionalMessage: Message | None = None


class DefaultRule(Rule):
    minimumSupportedVersion: int = Field(ge=0)


class Release(Model):
    default: DefaultRule
    channels: dict[Id, Rule] = Field(default_factory=dict)


class Draft(BaseModel):
    catalog: Catalog
    release: Release


def problems(error: ValidationError) -> list[dict[str, str]]:
    """Pydantic errors as [{path: "catalog.services[3].url", message: "…"}] for the dashboard."""
    found = []
    for item in error.errors():
        path = ""
        for part in item["loc"]:
            path += f"[{part}]" if isinstance(part, int) else (f".{part}" if path else str(part))
        message = item["msg"].removeprefix("Value error, ")
        found.append({"path": path, "message": message})
    return found


def normalize(draft: Draft) -> dict[str, Any]:
    """The documents as they are stored: no nulls, enums and lists as validated."""
    return {
        "catalog": draft.catalog.model_dump(mode="json", exclude_none=True),
        "release": draft.release.model_dump(mode="json", exclude_none=True),
    }
