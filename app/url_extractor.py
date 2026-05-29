import re

def extract_official_url_from_content(content, title=""):
    """Extract the best official URL from wiki page content."""
    if not content:
        return ""
    # Strategy 1: 来源说明 section
    sm = re.search("## \u6765\u6e90\u8bf4\u660e\s*\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
    if sm:
        sec = sm.group(1)
        urls = re.findall(r'https?://edu\.chengdu\.gov\.cn/[^\s)>"\'<>]+', sec)
        urls = [u.rstrip("*.,;:") for u in urls if "content_" in u or ".pdf" in u or ".shtml" in u]
        if urls:
            return urls[0]
        wx = re.findall(r'https?://mp\.weixin\.qq\.com/s/[^\s)>"\'<>]+', sec)
        wx = [u.rstrip("*.,;:") for u in wx]
        if wx:
            return wx[0]
        other = re.findall(r'https?://[^\s)>"\'<>]+', sec)
        hp = ["yjrx.cdeduypt.cn", "xqj.cdeduypt.cn", "whz.cdnet110.com", "online.cdzk.com", "mp.weixin.qq.com"]
        spec = [u.rstrip("*.,;:") for u in other
                if not any(u == "https://%s" % d or u == "https://%s/" % d for d in hp) and len(u) > 25]
        if spec:
            return spec[0]
    # Strategy 2: Full text scan
    allu = re.findall(r'https?://[^\s)>"\'<>]+', content)
    edu = [u.rstrip("*.,;:") for u in allu if "edu.chengdu.gov.cn" in u and ("content_" in u or ".pdf" in u)]
    if edu:
        return edu[0]
    wx2 = [u.rstrip("*.,;:") for u in allu if "mp.weixin.qq.com/s/" in u]
    if wx2:
        return wx2[0]
    # Strategy 3: Frontmatter url field
    fm = re.search(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if fm:
        fu = re.search(r'^url:\s*(https?://[^\s>]+)', fm.group(1), re.MULTILINE)
        if fu and len(fu.group(1)) > 10:
            return fu.group(1).rstrip("*.,;:")
    return ""
