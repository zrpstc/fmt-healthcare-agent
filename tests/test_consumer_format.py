from __future__ import annotations


from wgs_agent.consumer_web.format import (
    business_number_violations,
    count,
    pct,
    percentile_phrase,
    sig,
    text_violations,
    tier,
)


def test_percentage_rules_are_exact():
    assert pct(0.005) == "<0.01%"
    assert pct(0.017) == "0.017%"
    assert pct(0.075) == "0.075%"
    assert pct(0.105) == "0.11%"
    assert pct(0.196) == "0.20%"
    assert pct(0.999) == "1.0%"
    assert pct(1) == "1.0%"
    assert pct(13.657) == "13.7%"
    assert pct(24.777) == "24.8%"
    assert pct(99.97) == "100%"


def test_count_and_significant_digits():
    assert count(3537) == "3,537"
    assert sig(2.092606) == "2.09"
    assert sig(0.754748) == "0.755"
    assert sig(95.589) == "95.6"
    assert business_number_violations("对照人群：3,537名") == []
    assert business_number_violations("1234.5%") == ["1234.5"]
    assert business_number_violations("24.8%") == []


def test_percentile_phrase_never_prints_p_value():
    assert percentile_phrase(0.127) == "低于99%以上的参考人群"
    assert percentile_phrase(10.517) == "低于约89%的参考人群"
    assert percentile_phrase(68.306) == "高于约68%的参考人群"
    assert percentile_phrase(99.97) == "高于99%以上的参考人群"


def test_tier_labels_follow_the_metric_direction():
    low = tier(0.127, metric="richness")
    assert low.key == "very_low"
    assert low.label == "偏少"
    assert low.tone == "watch"
    borderline = tier(95.505, metric="evenness", borderline=True)
    assert borderline.key == "high"
    assert borderline.label == "较均衡"
    assert borderline.phrase == "高于约96%的参考人群"


def test_forbidden_words_are_detected():
    assert "未提供" in text_violations("未提供")
    assert "PWY-" in text_violations("PWY-6731")
    assert text_violations("肠道菌群的常见组成") == []
