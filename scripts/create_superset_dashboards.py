"""Create the Passenger and Airport Operations charts and dashboards in Superset."""
import json
import os

import requests


BASE = os.getenv("SUPERSET_URL", "http://localhost:8088")
USER = os.getenv("SUPERSET_ADMIN_USER", "admin")
PASSWORD = os.getenv("SUPERSET_ADMIN_PASSWORD", "admin")


def simple_metric(dataset, column, aggregate="MAX", name=None):
    label = name or f"{aggregate}({column})"
    return {
        "expressionType": "SIMPLE",
        "column": {"column_name": column},
        "aggregate": aggregate,
        "label": label,
        "optionName": f"metric_{dataset}_{column}",
    }


def count_metric(dataset):
    return {
        "expressionType": "SIMPLE",
        "column": {"column_name": "status"},
        "aggregate": "COUNT",
        "label": "COUNT(status)",
        "optionName": f"metric_{dataset}_count",
    }


def dashboard_position(chart_ids, chart_names):
    components = {
        "ROOT_ID": {
            "type": "ROOT",
            "id": "ROOT_ID",
            "children": ["GRID_ID"],
            "meta": {},
        },
        "GRID_ID": {
            "type": "GRID",
            "id": "GRID_ID",
            "children": [],
            "meta": {},
            "parents": ["ROOT_ID"],
        },
        "HEADER_ID": {
            "type": "HEADER",
            "id": "HEADER_ID",
            "meta": {"text": "", "headerSize": 2},
        },
    }

    for index, (chart_id, chart_name) in enumerate(zip(chart_ids, chart_names)):
        row_id = f"ROW-{index}"
        chart_id_key = f"CHART-{chart_id}"
        components["GRID_ID"]["children"].append(row_id)
        components[row_id] = {
            "type": "ROW",
            "id": row_id,
            "children": [chart_id_key],
            "parents": ["ROOT_ID", "GRID_ID"],
            "meta": {"background": "BACKGROUND_WHITE"},
        }
        components[chart_id_key] = {
            "type": "CHART",
            "id": chart_id_key,
            "children": [],
            "parents": ["ROOT_ID", "GRID_ID", row_id],
            "meta": {
                "width": 12,
                "height": 50,
                "chartId": chart_id,
                "sliceName": chart_name,
            },
        }
    components["DASHBOARD_VERSION_KEY"] = "v2"
    return json.dumps(components)


def airport_native_filter(dataset_ids, chart_ids, filter_id):
    return {
        "id": filter_id,
        "controlValues": {
            "enableEmptyFilter": False,
            "defaultToFirstItem": False,
            "multiSelect": False,
            "searchAllOptions": False,
            "inverseSelection": False,
        },
        "name": "Airport",
        "filterType": "filter_select",
        "targets": [
            {"datasetId": dataset_id, "column": {"name": "airport_code"}}
            for dataset_id in dataset_ids
        ],
        "defaultDataMask": {
            "extraFormData": {
                "filters": [{"col": "airport_code", "op": "IN", "val": ["BLR"]}]
            },
            "filterState": {"value": ["BLR"]},
            "ownState": {},
        },
        "cascadeParentIds": [],
        "scope": {"rootPath": ["ROOT_ID"], "excluded": []},
        "type": "NATIVE_FILTER",
        "chartsInScope": chart_ids,
        "tabsInScope": [],
    }


def main():
    session = requests.Session()
    login = session.post(
        f"{BASE}/api/v1/security/login",
        json={"username": USER, "password": PASSWORD, "provider": "db", "refresh": True},
        timeout=30,
    )
    login.raise_for_status()
    headers = {
        "Authorization": f"Bearer {login.json()['access_token']}",
        "Content-Type": "application/json",
    }

    datasets_response = session.get(f"{BASE}/api/v1/dataset/?q=(page_size:100)", headers=headers, timeout=30)
    datasets_response.raise_for_status()
    datasets = {
        item["table_name"]: item["id"]
        for item in datasets_response.json()["result"]
    }

    charts_response = session.get(f"{BASE}/api/v1/chart/?q=(page_size:500)", headers=headers, timeout=30)
    charts_response.raise_for_status()
    existing_charts = {
        item["slice_name"]: item["id"]
        for item in charts_response.json()["result"]
    }

    def create_chart(name, dataset, viz_type, params):
        if name in existing_charts:
            chart_id = existing_charts[name]
            response = session.put(
                f"{BASE}/api/v1/chart/{chart_id}",
                headers=headers,
                json={
                    "viz_type": viz_type,
                    "datasource_id": datasets[dataset],
                    "datasource_type": "table",
                    "params": json.dumps(params),
                },
                timeout=30,
            )
            response.raise_for_status()
            print(f"chart exists: {name}")
            return chart_id
        response = session.post(
            f"{BASE}/api/v1/chart/",
            headers=headers,
            json={
                "slice_name": name,
                "viz_type": viz_type,
                "datasource_id": datasets[dataset],
                "datasource_type": "table",
                "params": json.dumps(params),
            },
            timeout=30,
        )
        response.raise_for_status()
        chart_id = response.json()["id"]
        existing_charts[name] = chart_id
        print(f"chart created: {name} ({chart_id})")
        return chart_id

    passenger_specs = [
        ("Arrivals Today", "v_passenger_kpis", "big_number_total",
         {"metric": simple_metric("kpis", "arrivals_today"), "adhoc_filters": [], "time_range": "No filter",
          "header_font_size": 0.4, "subheader_font_size": 0.15, "y_axis_format": "SMART_NUMBER"}),
        ("Departures Today", "v_passenger_kpis", "big_number_total",
         {"metric": simple_metric("kpis", "departures_today"), "adhoc_filters": [], "time_range": "No filter",
          "header_font_size": 0.4, "subheader_font_size": 0.15, "y_axis_format": "SMART_NUMBER"}),
        ("Arrivals Next Hour", "v_passenger_kpis", "big_number_total",
         {"metric": simple_metric("kpis", "arrivals_next_hour"), "adhoc_filters": [], "time_range": "No filter",
          "header_font_size": 0.4, "subheader_font_size": 0.15, "y_axis_format": "SMART_NUMBER"}),
        ("Departures Next Hour", "v_passenger_kpis", "big_number_total",
         {"metric": simple_metric("kpis", "departures_next_hour"), "adhoc_filters": [], "time_range": "No filter",
          "header_font_size": 0.4, "subheader_font_size": 0.15, "y_axis_format": "SMART_NUMBER"}),
        ("Delayed and Cancelled", "v_passenger_kpis", "big_number_total",
         {"metric": simple_metric("kpis", "delayed_flights"), "adhoc_filters": [], "time_range": "No filter",
          "header_font_size": 0.4, "subheader_font_size": 0.15, "y_axis_format": "SMART_NUMBER"}),
        ("On-Time Percentage", "v_passenger_kpis", "big_number_total",
         {"metric": simple_metric("kpis", "on_time_percentage"), "adhoc_filters": [], "time_range": "No filter",
          "header_font_size": 0.4, "subheader_font_size": 0.15, "y_axis_format": ",.1f"}),
        ("Average Delay (min)", "v_passenger_kpis", "big_number_total",
         {"metric": simple_metric("kpis", "average_delay_min"), "adhoc_filters": [], "time_range": "No filter",
          "header_font_size": 0.4, "subheader_font_size": 0.15, "y_axis_format": ",.1f"}),
        ("Live Flight Information", "v_passenger_flights", "table",
         {"all_columns": ["airport_code", "flight_number", "airline", "direction", "city_airport", "scheduled_local",
                           "expected_local", "status", "terminal", "gate"],
          "adhoc_filters": [], "order_by_cols": ["[\"scheduled_local\",\"true\"]"],
          "page_length": 50, "table_timestamp_format": "smart_date", "color_pn": True}),
        ("Passenger Status Mix", "v_passenger_flights", "pie",
         {"groupby": ["status"], "metric": count_metric("passenger"), "adhoc_filters": [],
          "row_limit": 100, "show_labels": True, "show_legend": True}),
        ("Airport Weather", "v_weather_latest", "table",
         {"all_columns": ["airport_code", "temperature", "wind_speed", "visibility", "precipitation", "observed_local"],
          "adhoc_filters": [], "page_length": 50, "table_timestamp_format": "smart_date", "color_pn": True}),
    ]

    operations_specs = [
        ("Airborne and Ground Now", "v_aircraft_now", "big_number_total",
         {"metric": simple_metric("aircraft", "airborne_aircraft"), "adhoc_filters": [],
          "time_range": "No filter", "header_font_size": 0.4, "subheader_font_size": 0.15}),
        ("Ground Aircraft Now", "v_aircraft_now", "big_number_total",
         {"metric": simple_metric("aircraft", "ground_aircraft"), "adhoc_filters": [],
          "time_range": "No filter", "header_font_size": 0.4, "subheader_font_size": 0.15}),
        ("Arrivals and Departures per Hour", "v_hourly_ops", "echarts_timeseries_bar",
         {"x_axis": "hour_local",
          "metrics": [simple_metric("hourly", "arrivals"), simple_metric("hourly", "departures")],
          "groupby": [], "adhoc_filters": [], "row_limit": 100, "show_legend": True,
          "rich_tooltip": True, "y_axis_format": "SMART_NUMBER"}),
        ("Movements per 5 Minutes", "airport_metrics_5min", "echarts_timeseries_line",
         {"x_axis": "window_start",
          "metrics": [simple_metric("metrics", "total_movements")],
          "groupby": [], "adhoc_filters": [], "row_limit": 500, "show_legend": True,
          "rich_tooltip": True, "y_axis_format": "SMART_NUMBER"}),
        ("Congestion Index", "v_ops_current", "gauge_chart",
         {"metric": simple_metric("ops", "congestion_index"), "adhoc_filters": [],
          "min_val": 0, "max_val": 1, "show_percentage": True, "number_format": ".2f"}),
        ("Average Delay by Hour", "v_hourly_ops", "echarts_timeseries_line",
         {"x_axis": "hour_local",
          "metrics": [simple_metric("hourly", "avg_arrival_delay_min"),
                      simple_metric("hourly", "avg_departure_delay_min")],
          "groupby": [], "adhoc_filters": [], "row_limit": 100, "show_legend": True,
          "rich_tooltip": True, "y_axis_format": "SMART_NUMBER"}),
        ("Weather Risk", "v_ops_current", "table",
         {"all_columns": ["airport_code", "window_start", "weather_risk"], "adhoc_filters": [],
          "page_length": 50, "table_timestamp_format": "smart_date", "color_pn": True}),
        ("Delay vs Wind", "v_delay_vs_weather", "echarts_timeseries_scatter",
         {"x_axis": "avg_wind_kmh", "metrics": [simple_metric("delay", "avg_delay_min")],
          "groupby": [], "adhoc_filters": [], "row_limit": 500, "show_legend": True,
          "rich_tooltip": True, "y_axis_format": "SMART_NUMBER"}),
        ("Pipeline Health", "v_pipeline_status", "table",
         {"all_columns": ["component", "status", "records_published", "event_timestamp"],
          "adhoc_filters": [], "page_length": 50, "table_timestamp_format": "smart_date", "color_pn": True}),
    ]

    passenger_ids = [create_chart(*spec) for spec in passenger_specs]
    operations_ids = [create_chart(*spec) for spec in operations_specs]

    dashboards = [
        ("Passenger Dashboard", "passenger-dashboard", passenger_ids,
         [spec[0] for spec in passenger_specs], 5,
         ["v_passenger_kpis", "v_passenger_flights", "v_weather_latest"], passenger_ids),
        ("Airport Operations Dashboard", "airport-operations-dashboard", operations_ids,
         [spec[0] for spec in operations_specs], 5,
         ["v_aircraft_now", "v_hourly_ops", "airport_metrics_5min", "v_ops_current", "v_delay_vs_weather"],
         operations_ids[:-1]),
    ]

    existing_dashboards = session.get(
        f"{BASE}/api/v1/dashboard/?q=(page_size:100)",
        headers=headers,
        timeout=30,
    ).json()["result"]
    dashboards_by_slug = {item["slug"]: item["id"] for item in existing_dashboards if item.get("slug")}

    for (title, slug, chart_ids, chart_names, refresh_seconds,
         filter_datasets, filter_chart_ids) in dashboards:
        native_filter = airport_native_filter(
            [datasets[name] for name in filter_datasets],
            filter_chart_ids,
            f"NATIVE_FILTER-AIRPORT-{slug}",
        )
        metadata = {
            "refresh_frequency": refresh_seconds,
            "color_scheme": "supersetColors",
            "native_filter_configuration": [native_filter],
        }
        if slug in dashboards_by_slug:
            dashboard_id = dashboards_by_slug[slug]
            response = session.put(
                f"{BASE}/api/v1/dashboard/{dashboard_id}",
                headers=headers,
                json={
                    "dashboard_title": title,
                    "published": True,
                    "position_json": dashboard_position(chart_ids, chart_names),
                    "json_metadata": json.dumps(metadata),
                },
                timeout=30,
            )
            response.raise_for_status()
            print(f"dashboard updated: {title}")
        else:
            response = session.post(
                f"{BASE}/api/v1/dashboard/",
                headers=headers,
                json={
                    "dashboard_title": title,
                    "slug": slug,
                    "published": True,
                    "position_json": dashboard_position(chart_ids, chart_names),
                    "json_metadata": json.dumps(metadata),
                },
                timeout=30,
            )
            response.raise_for_status()
            dashboard_id = response.json()["id"]
            print(f"dashboard created: {title}")

        for chart_id in chart_ids:
            chart_response = session.put(
                f"{BASE}/api/v1/chart/{chart_id}",
                headers=headers,
                json={"dashboards": [dashboard_id]},
                timeout=30,
            )
            chart_response.raise_for_status()


if __name__ == "__main__":
    main()
