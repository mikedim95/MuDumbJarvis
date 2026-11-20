"""Read owner-published, centrally stored reference notes for chat and worker tasks."""
import re

FIELD = 'knowledge_publications'


def publications(agent):
    return ((agent.get('metadata') or {}).get('jarvis') or {}).get(FIELD) or {}


def overview(agent, query, *, budget=10000, relevant_only=False):
    entries = list(publications(agent).values())
    if not entries:
        return {}
    words = set(re.findall(r'[\w-]{3,}', query.casefold()))
    rows = []
    width = min(1800, budget - 80)
    for entry in reversed(entries):
        for block in entry['body'].split('\n\n'):
            for offset in range(0, len(block), width):
                paragraph = block[offset:offset + width]
                score = len(words.intersection(re.findall(r'[\w-]{3,}', paragraph.casefold())))
                if score or not relevant_only:
                    rows.append((score, entry['identifier'], paragraph))
    excerpts = []
    for _, source, paragraph in sorted(rows, key=lambda row:-row[0]):
        if len(paragraph) + 80 <= budget:
            excerpts.append({'source':source, 'text':paragraph})
            budget -= len(paragraph) + 80
    return {'scope':'General', 'publications':len(entries), 'excerpts':excerpts,
            'truncated':len(excerpts) < len(rows)}
