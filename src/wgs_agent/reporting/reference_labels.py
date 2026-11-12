"""Display labels come from the actual comparison provider, never a stale template."""

def short(inputs):
    comparison = inputs.get("healthy_comparison") or {}
    return "cMD" if (comparison.get("audit") or {}).get("provider") == "cmd" else "MHNO"


def title(inputs):
    audit = ((inputs.get("healthy_comparison") or {}).get("audit") or {})
    return audit.get("reference_population", "MHOmicrobiome MHNO")


def profile(inputs):
    return short(inputs) + " 独立谱"


def method(inputs):
    audit = ((inputs.get("healthy_comparison") or {}).get("audit") or {})
    if audit.get("provider") == "cmd":
        return "MetaPhlAn 3 / v30（待测3.0.14；来源小版本未公布）"
    return "MetaPhlAn 4.2.2 / Jan25"
