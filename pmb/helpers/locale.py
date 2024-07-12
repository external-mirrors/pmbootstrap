from pmb.helpers import logging


def get_keyboard_config(locale: str) -> str | None:
    xkb_layout = get_xkb_layout(locale)
    layout = None
    options = None
    if (xkb_layout is None
            or (xkb_layout.layout == "us" and xkb_layout.variant is None)):
        return None
    if xkb_layout.layout == "gb":
        layout = "gb"
    else:
        layout = f"us,{xkb_layout.layout}"
        options = "grp:alt_shift_toggle"
    variant = xkb_layout.variant if xkb_layout else None
    template = \
        f"""Section "InputClass"
\tIdentifier "keyboard"
\tMatchIsKeyboard "on"
\tOption "XkbLayout" "{layout}"
""" if layout else ""
    template += f"\tOption \"XkbVariants\" \",{variant}\"\n" if variant else ""
    template += f"\tOption \"XkbOptions\" \"{options}\"\n" if options else ""
    template += "EndSection"
    return template


class XkbLayout:
    def __init__(self,
                 layout: str | None = None,
                 variant: str | None = None):
        self.layout = layout
        self.variant = variant


def get_xkb_layout(locale: str) -> XkbLayout | None:
    """
    Get Xkb layout for the given locale.

    :param locale: Locale to get Xkblayout for.
    :type locale: str
    :return: Xkblayout for the given locale.
    :return: None if no Xkblayout found.
    :rtype: XkbLayout | None
    """
    try:
        (language, territory) = locale.split("_")
    except ValueError:
        return None

    lang_layouts = ["az", "bg", "csb", "cv", "dsb", "fi", "fo", "hr", "hu", "id", "is", "it", "lt", "lv", "mk", "mn",
                    "mt", "nl", "pl", "ro", "ru", "sk", "tg", "th", "tr", "uk", "uz"]

    if language in lang_layouts:
        return XkbLayout(language)
    elif language in lang_to_layout.keys():
        return XkbLayout(lang_to_layout[language])
    elif language == "af":
        return XkbLayout("za")
    elif language == "ak":
        return XkbLayout("gh", "akan")
    elif language == "ar":
        if territory == "DZ":
            return XkbLayout("dz", "ar")
        elif territory == "EG":
            return XkbLayout("eg")
        elif territory == "IQ":
            return XkbLayout("iq")
        elif territory == "MA":
            return XkbLayout("ma")
        elif territory == "SY":
            return XkbLayout("sy")
        else:
            return XkbLayout("ara")
    elif language == "as":
        return XkbLayout("in", "asm-kagapa")
    elif language == "ast":
        return XkbLayout("es", "ast")
    elif language == "ber":
        if territory == "DZ":
            return XkbLayout("dz")
        else:  # "MA"
            return XkbLayout("ma")
    elif language == "bo":
        return XkbLayout("cn", "tib")
    elif language == "ca":
        return XkbLayout("es", "cat")
    elif language == "chr":
        return XkbLayout("us", "chr")
    elif language == "crh":
        return XkbLayout("ua", "crh")
    elif language == "de":
        if territory == "AT":
            return XkbLayout("at")
        elif territory == "CH":
            return XkbLayout("ch")
        else:
            return XkbLayout("de")
    elif language == "en":
        if territory == "AU":
            return XkbLayout("au")
        elif territory == "CA":
            return XkbLayout("ca", "eng")
        elif territory == "GB":
            return XkbLayout("gb")
        elif territory == "IN":
            return XkbLayout("in", "eng")
        elif territory == "NG":
            return XkbLayout("ng")
        elif territory == "NZ":
            return XkbLayout("nz")
        elif territory == "ZA":
            return XkbLayout("za")
        else:
            return XkbLayout("us")
    elif language == "es":
        if territory in [
                "AR", "BO", "CL", "CO", "CR", "CU", "DO", "EC", "GT", "HN",
                "MX", "NI", "PA", "PE", "PR", "PY", "SV", "UY", "VE"]:
            return XkbLayout("latam")
        else:  # "ES", "US"
            return XkbLayout("es")
    elif language == "fr":
        if territory == "CA":
            return XkbLayout("ca")
        elif territory == "CH":
            return XkbLayout("ch", "fr")
        else:  # "FR"
            return XkbLayout("fr")
    elif language == "fur":
        return XkbLayout("it", "fur")
    elif language == "gu":
        return XkbLayout("in", "guj")
    elif language == "gv":
        return XkbLayout("gb", "gla")
    elif language == "ha":
        return XkbLayout("ng", "hausa")
    elif language == "hif":
        return XkbLayout("in")
    elif language == "hne":
        return XkbLayout("in")
    elif language == "ig":
        return XkbLayout("ng", "igbo")
    elif language == "iu":
        return XkbLayout("ca", "ike")
    elif language == "kab":
        return XkbLayout("dz", "azerty-deadkeys")
    elif language == "kn":
        return XkbLayout("in", "kan")
    elif language == "ku":
        return XkbLayout("tr", "ku")
    elif language == "mhr":
        return XkbLayout("ru", "chm")
    elif language == "ml":
        return XkbLayout("in", "mal")
    elif language == "mni":
        return XkbLayout("in", "mni")
    elif language == "mnw":
        return XkbLayout("mm", "mnw")
    elif language == "mr":
        return XkbLayout("in", "marathi")
    elif language == "nan":
        return XkbLayout("cn")  # Min Nan Chinese
    elif language == "nds":
        return XkbLayout("de")  # Low German
    elif language == "oc":
        return XkbLayout("fr", "oci")
    elif language == "or":
        return XkbLayout("in", "ori")
    elif language == "os":
        return XkbLayout("ru", "os_winkeys")
    elif language == "pa":
        return XkbLayout("in", "guru")
    elif language == "ps":
        return XkbLayout("af", "ps")
    elif language == "pt":
        if territory == "BR":
            return XkbLayout("br")
        else:  # if territory == "PT":
            return XkbLayout("pt")
    elif language == "sa":
        return XkbLayout("in", "sas")
    elif language == "sah":
        return XkbLayout("ru", "sah")
    elif language == "sat":
        return XkbLayout("in", "sat")
    elif language == "sd":
        return XkbLayout("in", "sdh")
    elif language == "se":
        return XkbLayout("no", "smi")
    elif language == "sgs":
        return XkbLayout("lt", "sgs")
    elif language == "shn":
        return XkbLayout("mm", "shn")
    elif language == "si":
        return XkbLayout("pk", "snd")
    elif language == "sw":
        if territory == "KE":
            return XkbLayout("ke")
        else:  # "TZ"
            return XkbLayout("tz")
    elif language == "szl":
        return XkbLayout("pl", "szl")
    elif language == "ta":
        if territory == "LK":
            return XkbLayout("lk", "tam_unicode")
        else:  # "IN"
            return XkbLayout("in", "tamilnet")
    elif language == "te":
        return XkbLayout("in", "tel")
    elif language == "tt":
        return XkbLayout("ru", "tt")
    elif language == "ug":
        return XkbLayout("cn", "ug")
    elif language == "ur":
        return XkbLayout("pak", "urd-nla")
    elif language == "yo":
        return XkbLayout("ng", "yoruba")
    elif language not in locales_without_layout:
        logging.warning(f"Language \"{language}\" not found in language list")
    return None


lang_to_layout = {
    "am": "et",
    "be": "by",
    "bn": "bd",
    "br": "bre",
    "bs": "ba",
    "cmn": "cn",
    "cs": "cz",
    "da": "dk",
    "dz": "bt",
    "el": "gr",
    "eo": "epo",
    "et": "ee",
    "eu": "es",
    "fa": "ir",
    "fil": "ph",
    "ga": "ie",
    "gd": "gla",
    "hak": "cn",
    "he": "il",
    "hi": "in",
    "hy": "am",
    "ja": "jp",
    "ka": "ge",
    "kk": "kz",
    "km": "kh",
    "ko": "kr",
    "ky": "kg",
    "lo": "la",
    "lzh": "cn",
    "mai": "in",
    "mi": "mao",
    "ms": "my",
    "my": "mm",
    "nb": "no",
    "ne": "np",
    "nn": "no",
    "sl": "si",
    "sq": "al",
    "sr": "rs",
    "sv": "se",
    "tk": "tm",
    "tl": "in",
    "tn": "bw",
    "vi": "vn",
    "wo": "sn",
    "yi": "il",
    "yue": "cn",
    "zh": "cn"
}
locales_without_layout = [
    "aa",  # Afar
    "agr",  # Aguaruna
    "an",  # Aragonese
    "anp",  # Angika
    "ayc",  # Aymara
    "bem",  # Bemba
    "bhb",  # Bhili
    "bho",  # Bhojpuri
    "bi",  # Bislama
    "bn",  # Bengali
    "brx",  # Bodo (India)
    "byn",  # Bilin
    "ce",  # Chechen
    "ch",  # Chamorro
    "cy",  # Wales
    "doi",  # Dogri
    "dv",  # Divehi
    "ff",  # Fulah
    "fy",  # Western Frisian
    "gez",  # Geez
    "gl",  # Galician
    "hsb",  # Upper Sorbian
    "ht",  # Haitian
    "ia",  # Interlingua
    "ik",  # Inupiaq
    "kl",  # Kalaallisut, Greenlandic
    "kok",  # Konkani
    "ks",  # Kashmiri
    "kw",  # Kinyarwanda
    "lb",  # Luxembourgish
    "lg",  # Ganda
    "li",  # Limburgish
    "lij",  # Ligurian
    "ln",  # Lingala
    "mfe",  # Morisyen
    "mg",  # Malagasy
    "miq",  # Miskito
    "mjw",  # Karbi
    "nhn",  # Nahuatl
    "niu",  # Niuean
    "nr",  # South Ndebele
    "nso",  # Northern Sotho
    "om",  # Oromo
    "pap",  # Papiamento
    "quz",  # Cusco Quechua
    "raj",  # Rajasthani
    "rw",  # Kinyarwanda
    "sc",  # Sardinian
    "shs",  # Shuswap
    "sid",  # Sidamo
    "sm",  # Samoan
    "so",  # Somali
    "ss",  # Swati
    "st",  # Southern Sotho
    "tcy",  # Tulu
    "the",  # Chitwania Tharu
    "ti",  # Tigrinya
    "tig",  # Tigre
    "to",  # Tonga
    "tpi",  # Tok Pisin
    "ts",  # Tsonga
    "unm",  # Unami
    "ve",  # Venda
    "wa",  # Walloon
    "wae",  # Walser
    "wal",  # Wolaitta
    "xh",  # Xhosa
    "yuw",  # Yau (Morobe province)
    "zu",  # Zulu
]
