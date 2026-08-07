from app.external_context.reference_repository import ReferenceDatasetRepository


def test_chengdu_2025_baseline_loads_with_city_metrics():
    dataset = ReferenceDatasetRepository().load_city("chengdu", 2025)

    assert dataset.dataset_id == "city-chengdu-2025"
    assert dataset.metrics["resident_population"].value == 2147.4
    assert dataset.metrics["food_service_revenue_growth"].value == 6.2


def test_milk_tea_2025_baseline_distinguishes_forecasts():
    dataset = ReferenceDatasetRepository().load_category("milk-tea", 2025)

    assert dataset.dataset_id == "category-milk-tea-2025"
    assert dataset.metrics["new_tea_market_size_2023"].status == "forecast"
    assert (
        dataset.metrics["made_to_order_tea_market_size_2023"].status
        == "estimated"
    )
    assert (
        dataset.metrics["new_tea_market_size_forecast_2025"].status
        == "forecast"
    )


def test_production_sources_use_public_https_urls():
    repository = ReferenceDatasetRepository()
    datasets = [
        repository.load_city("chengdu", 2025),
        repository.load_category("milk-tea", 2025),
    ]

    for dataset in datasets:
        assert dataset.sources
        assert all(
            str(source.url).startswith("https://") for source in dataset.sources
        )
        assert all(metric.source_ids for metric in dataset.metrics.values())
