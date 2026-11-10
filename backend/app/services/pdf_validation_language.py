"""Conservative language evidence for selecting original published text."""
from collections import Counter
import re
import unicodedata


WORDS = {
    "en": "the and of to in these this shall must regulations section under means for with by",
    "fr": "le la les des du et au aux dans pour règlement règlements doit une un est sur qui",
    "de": "der die das den dem des und ist sind für von mit nach eine einer einem werden wird",
    "es": "el los las del y en para por una un es que se deberá según este esta",
    "pt": "os as dos das uma um é são para por com que não artigo deverá este esta",
    "it": "il lo gli della dello delle e che per una sono alla nel nella deve articolo",
    "nl": "het een van voor met wordt worden deze dit op aan zijn moet volgens artikel",
}
WORDS = {code: set(value.split()) for code, value in WORDS.items()}
SCRIPTS = {code: re.compile(pattern) for code, pattern in {
    "ko": r"[\uac00-\ud7af\u1100-\u11ff]", "ja": r"[\u3040-\u30ff]", "han": r"[\u3400-\u9fff\U00020000-\U0002fa1f]",
    "ar": r"[\u0600-\u06ff\u0750-\u077f]", "he": r"[\u0590-\u05ff]", "el": r"[\u0370-\u03ff\u1f00-\u1fff]", "th": r"[\u0e00-\u0e7f]",
}.items()}


def language(text):
    text = unicodedata.normalize("NFKC", text[:120000]).casefold()
    letters = [char for char in text if char.isalpha()]
    if len(letters) < 20:
        return "unknown"
    scripts = Counter({code: len(pattern.findall("".join(letters))) for code, pattern in SCRIPTS.items()})
    for code in ("ko", "ja"):
        if scripts[code] >= 8 and scripts[code] + scripts["han"] > len(letters) * 0.6:
            return code
    for code in ("ar", "he", "el", "th"):
        if scripts[code] >= 12 and scripts[code] > len(letters) * 0.7:
            return {"ar": "und-Arab", "he": "und-Hebr", "el": "und-Grek", "th": "und-Thai"}[code]
    if scripts["han"] >= 12 and scripts["han"] > len(letters) * 0.7:
        return "und-Hani"
    words = Counter(re.findall(r"\w+", text))
    if sum("LATIN" in unicodedata.name(char, "") for char in letters) < len(letters) * 0.7:
        return "unknown"
    scores = sorted(((sum(words[word] for word in terms), code) for code, terms in WORDS.items()), reverse=True)
    return scores[0][1] if scores[0][0] >= 8 and scores[0][0] > scores[1][0] * 2 else "unknown"


def language_code(value):
    return (value or "").strip().lower().replace("_", "-").split("-")[0]


def select_html_language(upload, reference):
    groups = {}
    for unit in reference["units"]:
        code = language_code(unit.get("language"))
        if code:
            groups.setdefault(code, []).append(unit)
    if not groups:
        return None
    detected = upload.get("layout", {}).get("languages", ["unknown"])
    selected = detected[0] if len(detected) == 1 and detected[0] != "unknown" and not detected[0].startswith("und-") else None
    if selected is None and len(groups) > 1:
        def keys(units):
            text = " ".join(unit["text"] for unit in units)[:120000]
            text = unicodedata.normalize("NFKC", text).casefold()
            values = {value for value in re.findall(r"\w+", text) if len(value) >= 2}
            chars = re.findall(r"[\u3040-\u30ff\u3400-\u9fff]", text)
            values.update("".join(chars[index:index + 2]) for index in range(len(chars) - 1))
            return values
        actual = keys(upload["units"])
        scores = sorted(((len(actual & keys(units)) / max(1, len(actual)), code) for code, units in groups.items()), reverse=True)
        if len(actual) >= 12 and scores[0][0] >= 0.65 and scores[0][0] - scores[1][0] >= 0.35:
            selected = scores[0][1]
    if not selected or selected not in groups:
        return {"review": len(groups) > 1 or bool(selected), "language": None, "units": reference["units"]}
    units = [unit for unit in reference["units"] if not unit.get("language") or language_code(unit["language"]) == selected]
    return {"review": False, "language": selected, "units": units}
