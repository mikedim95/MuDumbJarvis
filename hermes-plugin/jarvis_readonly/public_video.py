"""Extract observed metadata from publicly readable YouTube pages."""
import json
import re

HOSTS = {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be'}
MAX_RESPONSE = 8 * 1024 * 1024


def text(value):
    if not isinstance(value, dict):
        return ''
    return value.get('simpleText') or ''.join(run.get('text', '') for run in value.get('runs', []))


def metadata(html):
    decoder = json.JSONDecoder()
    candidates = []
    for match in re.finditer(r'\b(?:var\s+)?(ytInitialPlayerResponse|ytInitialData)\s*=\s*', html):
        try:
            data = decoder.raw_decode(html[match.end():])[0]
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        if match[1] == 'ytInitialPlayerResponse' and data.get('videoDetails'):
            details = data['videoDetails']
            dates = (data.get('microformat') or {}).get('playerMicroformatRenderer') or {}
            return {'source_kind': 'public_video_metadata', 'title': details.get('title'),
                    'video_id': details.get('videoId'), 'channel': details.get('author'),
                    'published_at': dates.get('publishDate'), 'uploaded_at': dates.get('uploadDate'),
                    'playback_status': (data.get('playabilityStatus') or {}).get('status'),
                    'evidence': 'Observed public page metadata. The description is creator text. Video playback and transcript content have not been retrieved.',
                    'description': (details.get('shortDescription') or '')[:16000]}
        stack = [data]
        while stack and len(candidates) < 12:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(reversed(item))
            elif isinstance(item, dict):
                video = item.get('videoRenderer') or {}
                video_id = video.get('videoId') or ''
                if re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id) and not any(c['video_id'] == video_id for c in candidates):
                    snippets = [text(s.get('snippetText')) for s in video.get('detailedMetadataSnippets') or []]
                    candidates.append({'video_id': video_id, 'url': 'https://www.youtube.com/watch?v=' + video_id,
                        'title': text(video.get('title')), 'channel': text(video.get('ownerText')),
                        'published_hint': text(video.get('publishedTimeText')),
                        'snippet': '\n'.join(snippets) or text(video.get('descriptionSnippet'))})
                stack.extend(reversed(list(item.values())))
    if candidates:
        return {'source_kind': 'public_video_discovery', 'videos': candidates,
                'evidence': 'Search candidates only. Fetch each watch URL to verify its exact publication date and creator description. Relative dates and search snippets do not establish a publication year or a spoken tool mention.'}
    raise ValueError('The YouTube response contains no readable public video metadata. Report the access limitation.')
