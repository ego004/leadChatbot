import asyncio
import tempfile
import os
import re
from typing import List, Set, Deque
from urllib.parse import urlparse, urljoin, urldefrag
from collections import deque

import requests
from bs4 import BeautifulSoup


async def crawl_website(url: str, max_depth: int = 3, content_source: str = "fit_html", ignore_links: bool = True) -> List[str]:
    """
    Crawl a website and return list of markdown file paths
    
    Args:
        url: Website URL to crawl
        max_depth: Maximum depth for crawling (reduced from 10 to 3 for performance)
        content_source: Content source type
        ignore_links: Whether to ignore links in markdown
    
    Returns:
        List of file paths containing markdown content
    """
    # Run blocking crawl in a thread so our async endpoint doesn't block
    return await asyncio.to_thread(_crawl_sync, url, max_depth, ignore_links)


def _crawl_sync(seed_url: str, max_depth: int, ignore_links: bool, max_pages: int = 200) -> List[str]:
    session = requests.Session()
    session.headers.update({
        "User-Agent": "LeadGeniusBot/1.0 (+https://example.com/bot)"
    })

    temp_dir = tempfile.mkdtemp()
    saved_files: List[str] = []

    parsed_seed = urlparse(seed_url)
    seed_origin = f"{parsed_seed.scheme}://{parsed_seed.netloc}"
    seed_domain = parsed_seed.netloc

    def normalize_netloc(netloc: str) -> str:
        nl = netloc.lower()
        if nl.startswith("www."):
            nl = nl[4:]
        return nl

    seed_domain_norm = normalize_netloc(seed_domain)

    def is_binary_path(path: str) -> bool:
        return bool(re.search(r"\.(?:pdf|jpg|jpeg|png|gif|svg|webp|ico|mp4|mp3|zip|rar|gz|tar|7z|doc|docx|xls|xlsx)$", path, re.I))

    def normalize(u: str) -> str:
        u, _ = urldefrag(u)
        return u.rstrip("/")

    def same_domain(u: str) -> bool:
        try:
            return normalize_netloc(urlparse(u).netloc) == seed_domain_norm
        except Exception:
            return False

    def extract_links(html: str, base: str) -> List[str]:
        links: List[str] = []
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a.get("href")
            if not href:
                continue
            if href.startswith("mailto:") or href.startswith("javascript:"):
                continue
            abs_url = urljoin(base, href)
            if same_domain(abs_url) and not is_binary_path(urlparse(abs_url).path):
                links.append(normalize(abs_url))
        return links

    def to_markdown(html: str, page_url: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        # Remove scripts/styles
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        title = soup.title.string.strip() if soup.title and soup.title.string else page_url

        lines: List[str] = [f"# {title}", "", f"Source: {page_url}", ""]
        # Headings and paragraphs
        for elt in soup.find_all(["h1", "h2", "h3", "h4", "p", "li"]):
            name = elt.name.lower()
            text = " ".join(elt.get_text(" ").split())
            if not text:
                continue
            if name == "h1":
                lines.append(f"# {text}")
            elif name == "h2":
                lines.append(f"## {text}")
            elif name == "h3":
                lines.append(f"### {text}")
            elif name == "h4":
                lines.append(f"#### {text}")
            elif name == "li":
                lines.append(f"- {text}")
            else:
                lines.append(text)

        if not ignore_links:
            # Append a simple references section
            link_set = sorted(set(extract_links(html, page_url)))
            if link_set:
                lines.append("")
                lines.append("## Links")
                for l in link_set[:50]:
                    lines.append(f"- {l}")

        return "\n".join(lines)

    def save_markdown(page_url: str, markdown: str) -> str:
        safe = re.sub(r"[^a-zA-Z0-9_-]", "_", page_url)
        # Avoid overly long filenames
        if len(safe) > 200:
            safe = safe[:180]
        filename = f"{safe}.md"
        filepath = os.path.join(temp_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(markdown)
        return filepath

    def get(url: str) -> requests.Response | None:
        try:
            resp = session.get(url, timeout=12)
            ctype = resp.headers.get("Content-Type", "")
            if resp.status_code == 200 and "text/html" in ctype.lower():
                return resp
            return None
        except Exception:
            return None

    # 1) Collect seeds from sitemap.xml and robots.txt (if present)
    seeds: List[str] = []
    sitemap_candidates = [
        urljoin(seed_origin + "/", "sitemap.xml"),
        urljoin(seed_origin + "/", "sitemap_index.xml"),
    ]
    try:
        robots = session.get(urljoin(seed_origin + "/", "robots.txt"), timeout=8)
        if robots.status_code == 200:
            for line in robots.text.splitlines():
                if line.lower().startswith("sitemap:"):
                    sm_url = line.split(":", 1)[1].strip()
                    if same_domain(sm_url):
                        sitemap_candidates.append(sm_url)
    except Exception:
        pass

    seen_sitemaps: Set[str] = set()

    def parse_sitemap(sm_url: str) -> List[str]:
        urls: List[str] = []
        try:
            if sm_url in seen_sitemaps:
                return urls
            seen_sitemaps.add(sm_url)
            r = session.get(sm_url, timeout=10)
            if r.status_code != 200:
                return urls
            soup = BeautifulSoup(r.text, "xml")

            # urlset: direct list of page URLs
            urlset = soup.find("urlset")
            if urlset:
                for loc in urlset.find_all("loc"):
                    u = loc.get_text().strip()
                    if same_domain(u) and not is_binary_path(urlparse(u).path):
                        urls.append(normalize(u))
                return urls

            # sitemapindex: list of nested sitemap files
            sitemapindex = soup.find("sitemapindex")
            if sitemapindex:
                for sm in sitemapindex.find_all("sitemap"):
                    loc = sm.find("loc")
                    if not loc:
                        continue
                    child = loc.get_text().strip()
                    if same_domain(child):
                        urls.extend(parse_sitemap(child))
                return urls

            # Fallback: any <loc> entries
            for loc in soup.find_all("loc"):
                u = loc.get_text().strip()
                # If it's an HTML page, include; if it's another sitemap, recurse
                if u.lower().endswith((".xml", "/sitemap", "sitemap.xml")):
                    if same_domain(u):
                        urls.extend(parse_sitemap(u))
                elif same_domain(u) and not is_binary_path(urlparse(u).path):
                    urls.append(normalize(u))
        except Exception:
            return []
        return urls

    seen: Set[str] = set()
    for sm in sitemap_candidates:
        for u in parse_sitemap(sm)[:1000]:  # cap total extracted from sitemaps
            if u not in seen:
                seeds.append(u)
                seen.add(u)

    # Always include the seed page first
    seeds.insert(0, normalize(seed_url))

    # 2) BFS crawl within same domain
    visited: Set[str] = set()
    q: Deque[tuple[str, int]] = deque()
    for s in seeds:
        q.append((s, 0))

    pages_crawled = 0
    while q and pages_crawled < max_pages:
        current, depth = q.popleft()
        if current in visited:
            continue
        visited.add(current)

        if is_binary_path(urlparse(current).path):
            continue

        resp = get(current)
        if not resp:
            continue

        md = to_markdown(resp.text, current)
        path = save_markdown(current, md)
        saved_files.append(path)
        pages_crawled += 1

        if depth < max_depth:
            try:
                for link in extract_links(resp.text, current):
                    if link not in visited:
                        q.append((link, depth + 1))
            except Exception:
                pass

    return saved_files


def read_and_combine_markdown_files(file_paths: List[str]) -> str:
    """
    Read all markdown files and combine into single text
    
    Args:
        file_paths: List of markdown file paths
    
    Returns:
        Combined markdown content
    """
    combined_content = []
    
    for file_path in file_paths:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                if content.strip():  # Only add non-empty content
                    combined_content.append(content)
        except Exception as e:
            print(f"Error reading file {file_path}: {e}")
    
    return "\n\n---\n\n".join(combined_content)


def cleanup_temp_files(file_paths: List[str]):
    """Clean up temporary files after processing"""
    for file_path in file_paths:
        try:
            os.remove(file_path)
        except Exception as e:
            print(f"Error cleaning up file {file_path}: {e}")
    
    # Try to remove the temp directory
    if file_paths:
        temp_dir = os.path.dirname(file_paths[0])
        try:
            os.rmdir(temp_dir)
        except Exception as e:
            print(f"Error removing temp directory {temp_dir}: {e}")
