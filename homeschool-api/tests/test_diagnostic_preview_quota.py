"""
Real check for core/diagnostic_preview_quota.py — the per-IP cap on the
demo's diagnostic-preview feature (GET /diagnostic/summary, POST
/diagnostic/chat), added so the demo's own uncapped session length/message
count (core/demo_code_session.py) can't be paired with an uncapped
diagnostic preview to use the "demo" as ongoing free production.
"""

import core.diagnostic_preview_quota as quota


def setup_function():
    quota._usage = {}


def test_a_fresh_ip_has_quota():
    assert quota.has_quota("1.2.3.4", "111111") is True


def test_using_the_same_code_repeatedly_never_exhausts_quota():
    ip = "1.2.3.4"
    for _ in range(10):
        assert quota.has_quota(ip, "111111") is True
        quota.record_use(ip, "111111")


def test_quota_is_exhausted_after_the_limit_of_distinct_codes():
    ip = "1.2.3.4"
    for i in range(quota.DIAGNOSTIC_PREVIEW_QUOTA):
        code = f"{i:06d}"
        assert quota.has_quota(ip, code) is True
        quota.record_use(ip, code)

    assert quota.has_quota(ip, "999999") is False


def test_a_previously_used_code_still_has_quota_even_after_exhaustion():
    """Free re-access to a code already counted, even once the IP's
    overall quota for NEW codes is used up — the cap is on how many
    distinct sessions get evaluated, not on repeat visits to one."""
    ip = "1.2.3.4"
    for i in range(quota.DIAGNOSTIC_PREVIEW_QUOTA):
        code = f"{i:06d}"
        quota.record_use(ip, code)

    assert quota.has_quota(ip, "000000") is True


def test_different_ips_have_independent_quota():
    ip_a, ip_b = "1.2.3.4", "5.6.7.8"
    for i in range(quota.DIAGNOSTIC_PREVIEW_QUOTA):
        quota.record_use(ip_a, f"{i:06d}")

    assert quota.has_quota(ip_a, "999999") is False
    assert quota.has_quota(ip_b, "999999") is True


def test_record_use_is_idempotent_per_ip_and_code():
    ip = "1.2.3.4"
    for _ in range(5):
        quota.record_use(ip, "111111")
    assert len(quota._usage[ip]) == 1


def test_entries_older_than_the_window_are_pruned_and_free_up_quota():
    ip = "1.2.3.4"
    stale_cutoff = quota._WINDOW_SECONDS + 1
    quota._usage[ip] = [(f"{i:06d}", -stale_cutoff) for i in range(quota.DIAGNOSTIC_PREVIEW_QUOTA)]

    assert quota.has_quota(ip, "999999") is True


def test_pruning_a_fully_stale_ip_removes_its_dict_entry_entirely():
    ip = "1.2.3.4"
    stale_cutoff = quota._WINDOW_SECONDS + 1
    quota._usage[ip] = [("111111", -stale_cutoff)]

    quota._prune(ip)
    assert ip not in quota._usage
