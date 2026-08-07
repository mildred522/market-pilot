import os

import pytest

from app.external_context.baidu_client import BaiduMapClient


@pytest.mark.skipif(
    os.getenv("RUN_BAIDU_SMOKE") != "1" or not os.getenv("BAIDU_MAP_AK"),
    reason="real Baidu smoke test requires RUN_BAIDU_SMOKE=1 and BAIDU_MAP_AK",
)
def test_real_baidu_place_response_shape():
    result = BaiduMapClient.from_env().search_nearby_page(
        query="奶茶",
        latitude=30.5728,
        longitude=104.0668,
        radius_meters=800,
        page_num=0,
        page_size=20,
    )

    assert result.query == "奶茶"
    assert 0 <= result.total <= 150
    assert len(result.pois) <= 20
    assert all(poi.uid and poi.name for poi in result.pois)
