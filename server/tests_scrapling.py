"""Testes offline dos parsers da camada de coleta (sem rede).

Rodam com:  .venv/bin/python -m server.tests_scrapling
"""
import json

from server.scrapling_sources import (parse_count, parse_age_hours,
                                      parse_yt_initial_data,
                                      parse_tiktok_universal_data,
                                      google_trends_br)


def test_parse_count():
    assert parse_count("1.234.567 visualizações") == 1234567
    assert parse_count("1,2 mi de visualizações") == 1200000
    assert parse_count("12K views") == 12000
    assert parse_count("3,4 mil") == 3400
    assert parse_count(850) == 850
    assert parse_count(None) == 0
    assert parse_count("abc") == 0
    print("ok parse_count")


def test_parse_age():
    assert parse_age_hours("há 3 horas") == 3
    assert parse_age_hours("há 5 dias") == 120
    assert parse_age_hours("2 weeks ago") == 336
    assert parse_age_hours("") == 48
    print("ok parse_age_hours")


VIDEO1 = {
    "videoId": "abc123",
    "title": {"runs": [{"text": "Testei a garrafa "}]},
    "ownerText": {"runs": [{"text": "Canal Teste"}]},
    "viewCountText": {"simpleText": "1.234.567 visualizações"},
    "publishedTimeText": {"simpleText": "há 2 dias"},
    "lengthText": {"simpleText": "10:05"},
    "thumbnail": {"thumbnails": [
        {"url": "https://i.ytimg.com/small.jpg"},
        {"url": "https://i.ytimg.com/big.jpg"},
    ]},
}
VIDEO2 = {
    "videoId": "xyz789",
    "title": {"runs": [{"text": "Outro vídeo"}]},
    "ownerText": {"runs": [{"text": "Canal B"}]},
    "viewCountText": {"simpleText": "1,2 mi de visualizações"},
    "publishedTimeText": {"simpleText": "há 3 semanas"},
}


def test_parse_yt():
    item_section = {"itemSectionRenderer": {"contents": [
        {"videoRenderer": VIDEO1}, {"videoRenderer": VIDEO2}]}}
    data = {"contents": {"twoColumnSearchResultsRenderer": {"primaryContents": {
        "sectionListRenderer": {"contents": [item_section]}}}}}
    payload = json.dumps(data)  # valida a estrutura antes de injetar no HTML
    html = f"<html><script>var ytInitialData = {payload};</script></html>"
    vids = parse_yt_initial_data(html)
    assert len(vids) == 2, vids
    v = vids[0]
    assert v["id"] == "abc123"
    assert v["views"] == 1234567
    assert v["age_hours"] == 48
    assert v["duration"] == 605
    assert v["thumb"].endswith("big.jpg")
    assert vids[1]["views"] == 1200000
    assert parse_yt_initial_data("<html>nada aqui</html>") == []
    print("ok parse_yt_initial_data")


def test_parse_tiktok():
    import time as _t
    item1 = {"id": "700001", "desc": "olha isso #garrafa #viral",
             "createTime": int(_t.time()) - 3600 * 30,
             "author": {"uniqueId": "loja.teste", "nickname": "Loja Teste"},
             "video": {"duration": 21},
             "stats": {"playCount": 987654, "diggCount": 45000,
                       "commentCount": 1200, "shareCount": 800}}
    item2 = {"id": "700002", "desc": "segundo #achados",
             "author": {"uniqueId": "outro.user"},
             "stats": {"playCount": 123, "diggCount": 10,
                       "commentCount": 1, "shareCount": 0}}
    data = {"__DEFAULT_SCOPE__": {"webapp.video.search": {"itemList": [item1, item2]}}}
    payload = json.dumps(data)
    html = ('<html><script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" '
            f'type="application/json">{payload}</script></html>')
    vids = parse_tiktok_universal_data(html)
    assert len(vids) == 2, vids
    assert vids[0]["views"] == 987654
    assert vids[0]["likes"] == 45000
    assert vids[0]["handle"] == "@loja.teste"
    assert vids[0]["hashtags"] == ["#garrafa", "#viral"]
    assert 29 <= vids[0]["age_hours"] <= 31
    assert parse_tiktok_universal_data("<html></html>") == []
    print("ok parse_tiktok_universal_data")


def test_trends_parse():
    import server.scrapling_sources as ss
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:ht="https://trends.google.com/trending/rss">
<channel><item>
  <title>Assunto Quente</title>
  <ht:approx_traffic>200+</ht:approx_traffic>
  <ht:news><ht:newsItem><ht:newsItemTitle>Manchete</ht:newsItemTitle>
  <ht:newsItemSource>Portal X</ht:newsItemSource></ht:newsItem></ht:news>
</item><item>
  <title>Segundo Termo</title>
  <ht:approx_traffic>1.2 mi</ht:approx_traffic>
</item></channel></rss>"""
    original_fetch = ss._fetch

    class FakePage:
        body = xml

    ss._fetch = lambda *a, **k: FakePage()
    try:
        terms = google_trends_br(5)
    finally:
        ss._fetch = original_fetch
    assert len(terms) == 2, terms
    assert terms[0]["term"] == "Assunto Quente"
    assert terms[0]["traffic"] == 200
    assert terms[1]["traffic"] == 1200000
    print("ok google_trends parse")


if __name__ == "__main__":
    test_parse_count()
    test_parse_age()
    test_parse_yt()
    test_parse_tiktok()
    test_trends_parse()
    print("\nTODOS OS TESTES DE PARSING PASSARAM ✔")
