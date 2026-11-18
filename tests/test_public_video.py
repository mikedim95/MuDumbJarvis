"""Public video metadata stays bounded and does not invent missing dates or speech."""
import importlib
import json

import pytest
from test_employee_work import work


@pytest.fixture
def video(work):
    return importlib.import_module(work.module.__package__ + '.public_sources')


def test_search_candidates_require_watch_page_date_verification(video, monkeypatch):
    entries = [{'videoRenderer':{'videoId':'abcdefghijk', 'title':{'runs':[{'text':'A tool comparison'}]},
                'publishedTimeText':{'simpleText':'2 months ago'}}}]
    raw = ('<script>var ytInitialData = ' + json.dumps({'contents':entries}) + ';</script>').encode()
    monkeypatch.setattr(video,'fetch',lambda url:(raw,'text/html',url))
    source = video.document('https://www.youtube.com/results?search_query=tools')
    data = json.loads(source['text'])
    assert source['source_kind'] == 'public_video_discovery'
    assert data['videos'][0]['url'] == 'https://www.youtube.com/watch?v=abcdefghijk'
    assert data['videos'][0]['published_hint'] == '2 months ago'
    assert 'published_at' not in data['videos'][0]


def test_watch_metadata_preserves_exact_date_and_description(video, monkeypatch):
    player = {'videoDetails':{'videoId':'abcdefghijk', 'title':'Public demonstration',
              'shortDescription':'The author lists example-tool.', 'author':'Example channel'},
              'microformat':{'playerMicroformatRenderer':{'publishDate':'2026-10-15'}},
              'playabilityStatus':{'status':'LOGIN_REQUIRED'}}
    raw = ('<script>var ytInitialPlayerResponse = ' + json.dumps(player) + ';</script>').encode()
    monkeypatch.setattr(video,'fetch',lambda url:(raw,'text/html',url))
    data = json.loads(video.document('https://www.youtube.com/watch?v=abcdefghijk')['text'])
    assert data['published_at'] == '2026-10-15'
    assert data['description'] == 'The author lists example-tool.'
    assert data['playback_status'] == 'LOGIN_REQUIRED'
    assert 'transcript' not in data
    del player['microformat']
    raw = ('var ytInitialPlayerResponse = ' + json.dumps(player) + ';').encode()
    assert json.loads(video.document('https://www.youtube.com/watch?v=abcdefghijk')['text'])['published_at'] is None


def test_large_public_video_pages_have_a_separate_hard_limit(video, monkeypatch):
    class Response:
        status = 200
        def getheader(self, name): return 'text/html'
        def read(self, amount):
            limits.append(amount)
            return b'x' * min(amount,600000)
    class Connection:
        def __init__(self,*args): pass
        def request(self,*args,**kwargs): pass
        def getresponse(self): return Response()
        def close(self): pass
    limits = []
    monkeypatch.setattr(video,'PinnedHTTPS',Connection)
    monkeypatch.setattr(video,'destination',lambda url:(video.urllib.parse.urlsplit(url),video.urllib.parse.urlsplit(url).hostname,['8.8.8.8']))
    assert len(video.fetch('https://www.youtube.com/watch?v=abcdefghijk')[0]) == 600000
    assert limits[-1] == 8*1024*1024+1
    with pytest.raises(ValueError,match='512 KiB'):
        video.fetch('https://docs.example.com/tool')
    assert limits[-1] == 512*1024+1


def test_video_source_reports_do_not_require_internal_document_ids(work):
    source = {'source_kind':'public_video_metadata', 'framework':'document:0123456789abcdef',
              'blob_sha':'', 'sha256':'a'*64}
    work.module.validate_source_claims(work.turn, 'The creator description names example-tool.', [source])
