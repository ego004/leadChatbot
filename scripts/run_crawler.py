import argparse
import asyncio
import os
import sys
from typing import List

# Ensure project root is on sys.path so 'app' package is importable
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, os.pardir))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.services.crawler import (
    crawl_website,
    read_and_combine_markdown_files,
    cleanup_temp_files,
)
from app.services.llm_filter import markdown_filter


def print_sample(text: str, max_chars: int = 1200):
    snippet = text[:max_chars]
    print("\n===== CONTENT SAMPLE (truncated) =====\n")
    print(snippet)
    if len(text) > max_chars:
        print("\n... [truncated] ...\n")


async def main():
    parser = argparse.ArgumentParser(description="Run the crawler directly and preview output")
    parser.add_argument("url", help="Seed URL to crawl, e.g. https://orrya.co")
    # Also allow --url for convenience (user attempted this)
    parser.add_argument("--url", dest="url_opt", type=str, help="Seed URL (alternative to positional)")
    parser.add_argument("--max-depth", type=int, default=3, help="Maximum crawl depth (default: 3)")
    parser.add_argument(
        "--include-links",
        action="store_true",
        help="Include extracted links section in markdown",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep temporary markdown files instead of cleaning them up",
    )
    parser.add_argument(
        "--filter",
        action="store_true",
        help="Apply LLM filtering to the crawled markdowns (requires GOOGLE_API_KEY)",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        default=None,
        help="User prompt guiding the LLM filter (required when --filter is used)",
    )

    args = parser.parse_args()

    # Resolve seed URL, accept either positional or --url
    seed = args.url_opt or args.url
    if not seed.startswith("http://") and not seed.startswith("https://"):
        seed = "https://" + seed

    print(f"== CRAWL: {seed} (depth={args.max_depth}) ==")
    file_paths: List[str] = await crawl_website(
        url=seed,
        max_depth=args.max_depth,
        content_source="fit_html",
        ignore_links=not args.include_links,
    )

    print(f"Saved {len(file_paths)} markdown files")
    for p in file_paths[:10]:
        print(f" - {p}")
    if len(file_paths) > 10:
        print(f" ... and {len(file_paths) - 10} more")

    # Build markdown items (filename, content, source_url)
    def extract_source_url(md_text: str) -> str:
        for line in md_text.splitlines():
            if line.strip().lower().startswith("source:"):
                return line.split(":", 1)[1].strip()
        return seed
    items = []
    for p in file_paths:
        try:
            with open(p, "r", encoding="utf-8") as f:
                content = f.read()
                if content.strip():
                    items.append({
                        "filename": os.path.basename(p),
                        "content": content,
                        "source_url": extract_source_url(content),
                    })
        except Exception as e:
            print(f"Error reading file {p}: {e}")

    # Optional LLM filtering
    if args.filter:
        if not args.prompt:
            print("--prompt is required when using --filter. Skipping filtering.")
        elif not markdown_filter.is_available():
            print("LLM filtering not available (GOOGLE_API_KEY not set or model unavailable). Skipping filtering.")
        else:
            before = len(items)
            items = markdown_filter.filter_markdown_files(items, args.prompt)
            after = len(items)
            print(f"\nLLM filter applied: kept {after}/{before} markdowns.")

    # Combine (filtered or original) markdowns
    combined = "\n\n---\n\n".join(md["content"] for md in items)
    print(f"\nCombined length: {len(combined)} characters")
    print_sample(combined)

    if not args.keep_temp:
        cleanup_temp_files(file_paths)
        print("\nTemp files cleaned up.")
    else:
        print("\nTemp files kept (use --keep-temp to disable cleanup)")


if __name__ == "__main__":
    asyncio.run(main())
