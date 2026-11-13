import pytest
import re
import rstr

from sherlock_project.sherlock import sherlock
from sherlock_project.notify import QueryNotify
from sherlock_project.result import QueryResult, QueryStatus


FALSE_POSITIVE_ATTEMPTS: int = 2    # 随机生成的用户名可能恰好已被注册，因此允许重试。
FALSE_POSITIVE_QUANTIFIER_UPPER_BOUND: int = 15  # 限制 +、*、{n,} 等量词的重复次数上限；设为 0 时禁用限制。
FALSE_POSITIVE_DEFAULT_PATTERN: str = r'^[a-zA-Z0-9]{7,20}$'  # 未配置 regexCheck 时使用的默认规则。


def set_pattern_upper_bound(pattern: str, upper_bound: int = FALSE_POSITIVE_QUANTIFIER_UPPER_BOUND) -> str:
    """为使用 +、* 或 {n,} 等量词的正则表达式设置重复次数上限。"""
    def replace_upper_bound(match: re.Match) -> str: # type: ignore
        lower_bound: int = int(match.group(1)) if match.group(1) else 0 # type: ignore
        nonlocal upper_bound
        upper_bound = upper_bound if lower_bound < upper_bound else lower_bound # type: ignore  # noqa: F823
        return f'{{{lower_bound},{upper_bound}}}'

    pattern = re.sub(r'(?<!\\)\{(\d+),\}', replace_upper_bound, pattern) # {n,} # type: ignore
    pattern = re.sub(r'(?<!\\)\+', f'{{1,{upper_bound}}}', pattern) # +
    pattern = re.sub(r'(?<!\\)\*', f'{{0,{upper_bound}}}', pattern) # *

    return pattern

def false_positive_check(sites_info: dict[str, dict[str, str]], site: str, pattern: str) -> QueryStatus:
    """检查站点是否容易产生误报。"""
    status: QueryStatus = QueryStatus.UNKNOWN

    for _ in range(FALSE_POSITIVE_ATTEMPTS):
        query_notify: QueryNotify = QueryNotify()
        username: str = rstr.xeger(pattern)

        result: QueryResult | str = sherlock(
            username=username,
            site_data=sites_info,
            query_notify=query_notify,
        )[site]['status']

        if not hasattr(result, 'status'):
            raise TypeError(f"Result for site {site} does not have 'status' attribute. Actual result: {result}")
        if type(result.status) is not QueryStatus: # type: ignore
            raise TypeError(f"Result status for site {site} is not of type QueryStatus. Actual type: {type(result.status)}") # type: ignore
        status = result.status # type: ignore

        if status in (QueryStatus.AVAILABLE, QueryStatus.WAF):
            return status

    return status


def false_negative_check(sites_info: dict[str, dict[str, str]], site: str) -> QueryStatus:
    """检查站点是否容易产生漏报。"""
    status: QueryStatus = QueryStatus.UNKNOWN
    query_notify: QueryNotify = QueryNotify()

    result: QueryResult | str = sherlock(
        username=sites_info[site]['username_claimed'],
        site_data=sites_info,
        query_notify=query_notify,
    )[site]['status']

    if not hasattr(result, 'status'):
            raise TypeError(f"Result for site {site} does not have 'status' attribute. Actual result: {result}")
    if type(result.status) is not QueryStatus: # type: ignore
        raise TypeError(f"Result status for site {site} is not of type QueryStatus. Actual type: {type(result.status)}") # type: ignore
    status = result.status # type: ignore

    return status

@pytest.mark.validate_targets
@pytest.mark.online
class Test_All_Targets:

    @pytest.mark.validate_targets_fp
    def test_false_pos(self, chunked_sites: dict[str, dict[str, str]]):
        """遍历站点清单，找出可能产生误报的站点。"""
        pattern: str
        for site in chunked_sites:
            try:
                pattern = chunked_sites[site]['regexCheck']
            except KeyError:
                pattern = FALSE_POSITIVE_DEFAULT_PATTERN

            if FALSE_POSITIVE_QUANTIFIER_UPPER_BOUND > 0:
                pattern = set_pattern_upper_bound(pattern)

            result: QueryStatus = false_positive_check(chunked_sites, site, pattern)
            assert result is QueryStatus.AVAILABLE, f"{site} produced false positive with pattern {pattern}, result was {result}"

    @pytest.mark.validate_targets_fn
    def test_false_neg(self, chunked_sites: dict[str, dict[str, str]]):
        """遍历站点清单，找出可能产生漏报的站点。"""
        for site in chunked_sites:
            result: QueryStatus = false_negative_check(chunked_sites, site)
            assert result is QueryStatus.CLAIMED, f"{site} produced false negative, result was {result}"

