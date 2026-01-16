
def _generate_html_report(results, query, filename, highlight_terms=None):
    """Generates a standalone HTML report for search results with optional keyword highlighting."""
    import html
    import time
    import re
    
    def apply_highlights(text, terms):
        """Wrap matching terms in <mark> tags."""
        if not terms:
            return text
        for term in terms:
            if len(term) < 3:
                continue
            escaped = re.escape(term)
            pattern = re.compile(f"({escaped})", re.IGNORECASE)
            text = pattern.sub(r'<mark>\1</mark>', text)
        return text
    
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Search Results: {html.escape(query)}</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
        :root {{ --primary: #ff4500; --bg: #0b0e11; --surface: #151a21; --border: #2d333b; --text: #f0f6fc; --text-secondary: #8b949e; --accent: #2b7bd6; --highlight: rgba(255, 165, 0, 0.35); }}
        body {{ font-family: 'Inter', -apple-system, sans-serif; background-color: var(--bg); color: var(--text); margin: 0; padding: 40px 20px; line-height: 1.6; }}
        .container {{ max-width: 900px; margin: 0 auto; }}
        .header {{ margin-bottom: 40px; border-left: 4px solid var(--primary); padding-left: 20px; }}
        h1 {{ font-size: 2.5em; font-weight: 700; margin: 0 0 10px 0; letter-spacing: -0.02em; }}
        .meta {{ color: var(--text-secondary); font-size: 0.9em; }}
        .card {{ background-color: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 30px; margin-bottom: 25px; transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1); box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); }}
        .card:hover {{ border-color: var(--accent); transform: translateY(-2px); box-shadow: 0 10px 15px -3px rgba(0,0,0,0.2); }}
        .card-header {{ display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px; }}
        .score-badge {{ background: linear-gradient(135deg, var(--primary), #ff6a00); color: white; padding: 4px 12px; border-radius: 20px; font-weight: 600; font-size: 0.85em; box-shadow: 0 2px 4px rgba(255,69,0,0.3); }}
        .sub-link {{ color: var(--accent); font-size: 0.9em; font-weight: 600; text-decoration: none; }}
        .post-date {{ color: var(--text-secondary); font-size: 0.8em; margin-top: 4px; }}
        .title {{ font-size: 1.4em; font-weight: 600; margin: 0 0 15px 0; display: block; color: var(--text); text-decoration: none; line-height: 1.3; }}
        .title:hover {{ color: var(--accent); }}
        .content {{ color: #c9d1d9; font-size: 1em; white-space: pre-wrap; overflow-wrap: break-word; background: rgba(0,0,0,0.2); padding: 20px; border-radius: 8px; border-left: 2px solid var(--border); }}
        .content.collapsed {{ max-height: 150px; overflow: hidden; position: relative; mask-image: linear-gradient(to bottom, black 50%, transparent 100%); }}
        .show-toggle {{ background: none; border: none; color: var(--accent); cursor: pointer; font-size: 0.9em; padding: 10px 0; font-weight: 600; display: block; }}
        .tag-list {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 20px; padding-top: 15px; border-top: 1px solid var(--border); }}
        .tag-pill {{ font-size: 0.75em; padding: 3px 10px; border-radius: 12px; background: rgba(43, 123, 214, 0.1); border: 1px solid rgba(43, 123, 214, 0.3); color: var(--accent); }}
        .card-footer {{ margin-top: 20px; padding-top: 15px; border-top: 1px solid var(--border); display: flex; gap: 15px; font-size: 0.8em; color: var(--text-secondary); }}
        mark {{ background-color: var(--highlight); color: var(--text); padding: 1px 3px; border-radius: 3px; }}
    </style>
    <script>
        function toggleContent(btn) {{
            const card = btn.closest('.card');
            const content = card.querySelector('.content');
            const isCollapsed = content.classList.contains('collapsed');
            if (isCollapsed) {{
                content.classList.remove('collapsed');
                btn.innerText = 'Show Less ↑';
            }} else {{
                content.classList.add('collapsed');
                btn.innerText = 'Show More ↓';
                card.scrollIntoView({{ behavior: 'smooth', block: 'nearest' }});
            }}
        }}
    </script>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Search Results</h1>
            <div class="meta">Query: {html.escape(query)}<br>Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}<br>Results: {len(results)}</div>
        </div>
"""
    for i, p in enumerate(results):
        score = p.get('score', 0)
        try: score_val = float(score)
        except: score_val = 0
        
        title = html.escape(p.get('title', 'No Title'))
        sub = html.escape(p.get('sub', 'Unknown'))
        content = html.escape(p.get('content', ''))
        url = p.get('url', '#')
        
        timestamp = p.get('timestamp')
        date_str = time.strftime('%Y-%m-%d', time.gmtime(timestamp)) if timestamp else 'Unknown Date'
        
        tags = p.get('tags', [])
        tags_html = ""
        if tags:
            tags_html = '<div class="tag-list">' + "".join([f'<span class="tag-pill">{html.escape(t)}</span>' for t in tags[:8]]) + '</div>'

        # Apply highlighting if terms provided
        if highlight_terms:
            title = apply_highlights(title, highlight_terms)
            content = apply_highlights(content, highlight_terms)
        
        is_long = len(content) > 600
        
        html_content += f"""
        <div class="card">
            <div class="card-header">
                <div>
                    <span class="sub-link">r/{sub}</span>
                    <div class="post-date">{date_str}</div>
                </div>
                <div style="display:flex; align-items:center; gap:10px;">
                    <span style="font-size:1.2rem; color:#4a5568;" title="Favorites disabled in offline report">☆</span>
                    <span class="score-badge">{score_val:.1f}</span>
                </div>
            </div>
            <a href="{url}" target="_blank" class="title">{title}</a>
            <div class="content {'collapsed' if is_long else ''}">{content}</div>
            {f'<button class="show-toggle" onclick="toggleContent(this)">Show More ↓</button>' if is_long else ''}
            {tags_html}
        </div>"""

    html_content += """
    </div>
</body>
</html>"""
    
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write(html_content)
        return True
    except Exception as e:
        print(f"Error saving HTML report: {e}")
        return False
