"""Create airport-wise Passenger and Airport Operations charts and dashboards in Superset."""
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
        "optionName": f"metric_{dataset}_{column}_{aggregate.lower()}",
    }


def count_metric(dataset):
    return {
        "expressionType": "SIMPLE",
        "column": {"column_name": "status"},
        "aggregate": "COUNT",
        "label": "COUNT(status)",
        "optionName": f"metric_{dataset}_count",
    }


def dashboard_position(rows):
    """Build a multi-column Superset v2 grid layout from rows of (chart_id, chart_name, width, height)."""
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

    for row_idx, row in enumerate(rows):
        row_id = f"ROW-{row_idx}"
        components["GRID_ID"]["children"].append(row_id)
        row_children = []
        for chart_id, chart_name, width, height in row:
            chart_key = f"CHART-{chart_id}"
            row_children.append(chart_key)
            components[chart_key] = {
                "type": "CHART",
                "id": chart_key,
                "children": [],
                "parents": ["ROOT_ID", "GRID_ID", row_id],
                "meta": {
                    "width": width,
                    "height": height,
                    "chartId": chart_id,
                    "sliceName": chart_name,
                },
            }
        components[row_id] = {
            "type": "ROW",
            "id": row_id,
            "children": row_children,
            "parents": ["ROOT_ID", "GRID_ID"],
            "meta": {"background": "BACKGROUND_TRANSPARENT"},
        }

    components["DASHBOARD_VERSION_KEY"] = "v2"
    return json.dumps(components)


def column_native_filter(name, column, dataset_ids, chart_ids, filter_id, multi_select=True):
    return {
        "id": filter_id,
        "controlValues": {
            "enableEmptyFilter": False,
            "defaultToFirstItem": False,
            "multiSelect": multi_select,
            "searchAllOptions": False,
            "inverseSelection": False,
        },
        "name": name,
        "filterType": "filter_select",
        "targets": [
            {"datasetId": dataset_id, "column": {"name": column}}
            for dataset_id in dataset_ids
        ],
        "defaultDataMask": {
            "extraFormData": {},
            "filterState": {},
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

    def upsert_chart(name, dataset, viz_type, params):
        payload = {
            "viz_type": viz_type,
            "datasource_id": datasets[dataset],
            "datasource_type": "table",
            "params": json.dumps(params),
        }
        if name in existing_charts:
            chart_id = existing_charts[name]
            response = session.put(f"{BASE}/api/v1/chart/{chart_id}", headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            print(f"chart updated: {name} ({chart_id})")
            return chart_id
        payload["slice_name"] = name
        response = session.post(f"{BASE}/api/v1/chart/", headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        chart_id = response.json()["id"]
        existing_charts[name] = chart_id
        print(f"chart created: {name} ({chart_id})")
        return chart_id

    def big_num(dataset, col, agg="SUM", fmt="SMART_NUMBER"):
        return {
            "metric": simple_metric(dataset, col, aggregate=agg),
            "adhoc_filters": [],
            "time_range": "No filter",
            "header_font_size": 0.4,
            "subheader_font_size": 0.15,
            "y_axis_format": fmt,
        }

    # ---------------- Passenger Dashboard charts (airport-wise + multi-airport filterable)
    p_arrivals = upsert_chart("Arrivals Today", "v_passenger_kpis", "big_number_total", big_num("kpis", "arrivals_today", "SUM"))
    p_departures = upsert_chart("Departures Today", "v_passenger_kpis", "big_number_total", big_num("kpis", "departures_today", "SUM"))
    p_ontime = upsert_chart("On-Time Percentage", "v_passenger_kpis", "big_number_total", big_num("kpis", "on_time_percentage", "AVG", ",.1f"))
    p_arr_next = upsert_chart("Arrivals Next Hour", "v_passenger_kpis", "big_number_total", big_num("kpis", "arrivals_next_hour", "SUM"))
    p_dep_next = upsert_chart("Departures Next Hour", "v_passenger_kpis", "big_number_total", big_num("kpis", "departures_next_hour", "SUM"))
    p_delayed = upsert_chart("Delayed and Cancelled", "v_passenger_kpis", "big_number_total", big_num("kpis", "delayed_flights", "SUM"))
    p_avg_delay = upsert_chart("Average Delay (min)", "v_passenger_kpis", "big_number_total", big_num("kpis", "average_delay_min", "AVG", ",.1f"))

    p_kpis_table = upsert_chart(
        "Airport-Wise Passenger KPIs",
        "v_passenger_kpis",
        "table",
        {
            "all_columns": [
                "airport_code", "arrivals_today", "departures_today", "arrivals_next_hour",
                "departures_next_hour", "delayed_flights", "cancelled_flights",
                "on_time_percentage", "average_delay_min",
            ],
            "adhoc_filters": [],
            "order_by_cols": ['["airport_code","true"]'],
            "page_length": 25,
            "table_timestamp_format": "smart_date",
            "color_pn": True,
        },
    )
    p_flights_by_ap = upsert_chart(
        "Arrivals & Departures by Airport",
        "v_passenger_kpis",
        "echarts_timeseries_bar",
        {
            "x_axis": "airport_code",
            "metrics": [
                simple_metric("kpis", "arrivals_today", "MAX", "Arrivals"),
                simple_metric("kpis", "departures_today", "MAX", "Departures"),
            ],
            "groupby": [],
            "adhoc_filters": [],
            "row_limit": 25,
            "show_legend": True,
            "rich_tooltip": True,
            "y_axis_format": "SMART_NUMBER",
        },
    )
    p_otp_by_ap = upsert_chart(
        "On-Time % & Avg Delay by Airport",
        "v_passenger_kpis",
        "echarts_timeseries_bar",
        {
            "x_axis": "airport_code",
            "metrics": [
                simple_metric("kpis", "on_time_percentage", "MAX", "On-Time %"),
                simple_metric("kpis", "average_delay_min", "MAX", "Avg Delay (min)"),
            ],
            "groupby": [],
            "adhoc_filters": [],
            "row_limit": 25,
            "show_legend": True,
            "rich_tooltip": True,
            "y_axis_format": ",.1f",
        },
    )
    p_weather = upsert_chart(
        "Airport Weather",
        "v_weather_latest",
        "table",
        {
            "all_columns": [
                "airport_code", "temperature", "wind_speed", "visibility",
                "precipitation", "weather_risk", "observed_local",
            ],
            "adhoc_filters": [],
            "order_by_cols": ['["airport_code","true"]'],
            "page_length": 25,
            "table_timestamp_format": "smart_date",
            "color_pn": True,
        },
    )
    p_fids = upsert_chart(
        "Live Flight Information",
        "v_passenger_flights",
        "table",
        {
            "all_columns": [
                "airport_code", "flight_number", "airline", "direction", "city_airport",
                "scheduled_local", "expected_local", "delay_minutes", "status", "terminal", "gate",
            ],
            "adhoc_filters": [],
            "order_by_cols": ['["scheduled_local","true"]'],
            "page_length": 50,
            "table_timestamp_format": "smart_date",
            "color_pn": True,
        },
    )
    p_status_mix = upsert_chart(
        "Passenger Status Mix",
        "v_passenger_flights",
        "pie",
        {
            "groupby": ["status"],
            "metric": count_metric("passenger"),
            "adhoc_filters": [],
            "row_limit": 100,
            "show_labels": True,
            "show_legend": True,
        },
    )

    passenger_rows = [
        [(p_arrivals, "Arrivals Today", 4, 24), (p_departures, "Departures Today", 4, 24), (p_ontime, "On-Time Percentage", 4, 24)],
        [(p_arr_next, "Arrivals Next Hour", 3, 22), (p_dep_next, "Departures Next Hour", 3, 22), (p_delayed, "Delayed and Cancelled", 3, 22), (p_avg_delay, "Average Delay (min)", 3, 22)],
        [(p_kpis_table, "Airport-Wise Passenger KPIs", 6, 42), (p_flights_by_ap, "Arrivals & Departures by Airport", 6, 42)],
        [(p_otp_by_ap, "On-Time % & Avg Delay by Airport", 6, 42), (p_weather, "Airport Weather", 6, 42)],
        [(p_fids, "Live Flight Information", 8, 56), (p_status_mix, "Passenger Status Mix", 4, 56)],
    ]
    passenger_ids = [cid for row in passenger_rows for cid, _, _, _ in row]

    # ---------------- Airport Operations Dashboard charts (airport-wise)
    o_airborne = upsert_chart("Airborne and Ground Now", "v_aircraft_now", "big_number_total", big_num("aircraft", "airborne_aircraft", "SUM"))
    o_ground = upsert_chart("Ground Aircraft Now", "v_aircraft_now", "big_number_total", big_num("aircraft", "ground_aircraft", "SUM"))
    o_airspace_tbl = upsert_chart(
        "Live Airspace by Airport",
        "v_aircraft_now",
        "table",
        {
            "all_columns": ["airport_code", "airborne_aircraft", "ground_aircraft", "tracked_aircraft"],
            "adhoc_filters": [],
            "order_by_cols": ['["airport_code","true"]'],
            "page_length": 25,
            "table_timestamp_format": "smart_date",
            "color_pn": True,
        },
    )
    o_ops_tbl = upsert_chart(
        "Current Operations by Airport",
        "v_ops_current",
        "table",
        {
            "all_columns": [
                "airport_code", "arrivals", "departures", "total_movements",
                "congestion_index", "congestion_level", "weather_risk", "window_start",
            ],
            "adhoc_filters": [],
            "order_by_cols": ['["airport_code","true"]'],
            "page_length": 25,
            "table_timestamp_format": "smart_date",
            "color_pn": True,
        },
    )
    o_airspace_bar = upsert_chart(
        "Airborne vs Ground by Airport",
        "v_aircraft_now",
        "echarts_timeseries_bar",
        {
            "x_axis": "airport_code",
            "metrics": [
                simple_metric("aircraft", "airborne_aircraft", "MAX", "Airborne"),
                simple_metric("aircraft", "ground_aircraft", "MAX", "On Ground"),
            ],
            "groupby": [],
            "adhoc_filters": [],
            "row_limit": 25,
            "show_legend": True,
            "rich_tooltip": True,
            "y_axis_format": "SMART_NUMBER",
        },
    )
    o_congestion_bar = upsert_chart(
        "Congestion Index by Airport",
        "v_ops_current",
        "echarts_timeseries_bar",
        {
            "x_axis": "airport_code",
            "metrics": [simple_metric("ops", "congestion_index", "MAX", "Congestion Index")],
            "groupby": [],
            "adhoc_filters": [],
            "row_limit": 25,
            "show_legend": True,
            "rich_tooltip": True,
            "y_axis_format": ",.2f",
        },
    )
    o_mov_5min = upsert_chart(
        "Movements per 5 Minutes",
        "airport_metrics_5min",
        "echarts_timeseries_line",
        {
            "x_axis": "window_start",
            "metrics": [simple_metric("metrics", "total_movements", "MAX", "Movements")],
            "groupby": ["airport_code"],
            "adhoc_filters": [],
            "row_limit": 500,
            "show_legend": True,
            "rich_tooltip": True,
            "y_axis_format": "SMART_NUMBER",
        },
    )
    o_hourly = upsert_chart(
        "Arrivals and Departures per Hour",
        "v_hourly_ops",
        "echarts_timeseries_bar",
        {
            "x_axis": "hour_local",
            "metrics": [
                simple_metric("hourly", "arrivals", "MAX", "Arrivals"),
                simple_metric("hourly", "departures", "MAX", "Departures"),
            ],
            "groupby": ["airport_code"],
            "adhoc_filters": [],
            "row_limit": 200,
            "show_legend": True,
            "rich_tooltip": True,
            "y_axis_format": "SMART_NUMBER",
        },
    )
    o_delay_hr = upsert_chart(
        "Average Delay by Hour",
        "v_hourly_ops",
        "echarts_timeseries_line",
        {
            "x_axis": "hour_local",
            "metrics": [
                simple_metric("hourly", "avg_arrival_delay_min", "MAX", "Arrival Delay"),
                simple_metric("hourly", "avg_departure_delay_min", "MAX", "Departure Delay"),
            ],
            "groupby": ["airport_code"],
            "adhoc_filters": [],
            "row_limit": 200,
            "show_legend": True,
            "rich_tooltip": True,
            "y_axis_format": ",.1f",
        },
    )
    o_delay_wind = upsert_chart(
        "Delay vs Wind",
        "v_delay_vs_weather",
        "echarts_timeseries_scatter",
        {
            "x_axis": "avg_wind_kmh",
            "metrics": [simple_metric("delay", "avg_delay_min", "MAX", "Avg Delay (min)")],
            "groupby": ["airport_code"],
            "adhoc_filters": [],
            "row_limit": 500,
            "show_legend": True,
            "rich_tooltip": True,
            "y_axis_format": ",.1f",
        },
    )
    o_weather_risk = upsert_chart(
        "Weather Risk",
        "v_ops_current",
        "table",
        {
            "all_columns": ["airport_code", "window_start", "congestion_level", "weather_risk"],
            "adhoc_filters": [],
            "order_by_cols": ['["airport_code","true"]'],
            "page_length": 25,
            "table_timestamp_format": "smart_date",
            "color_pn": True,
        },
    )
    o_pipeline = upsert_chart(
        "Pipeline Health",
        "v_pipeline_status",
        "table",
        {
            "all_columns": ["component", "status", "records_published", "event_timestamp"],
            "adhoc_filters": [],
            "page_length": 50,
            "table_timestamp_format": "smart_date",
            "color_pn": True,
        },
    )

    operations_rows = [
        [(o_airborne, "Airborne and Ground Now", 6, 24), (o_ground, "Ground Aircraft Now", 6, 24)],
        [(o_airspace_tbl, "Live Airspace by Airport", 6, 40), (o_ops_tbl, "Current Operations by Airport", 6, 40)],
        [(o_airspace_bar, "Airborne vs Ground by Airport", 6, 42), (o_congestion_bar, "Congestion Index by Airport", 6, 42)],
        [(o_mov_5min, "Movements per 5 Minutes", 6, 45), (o_hourly, "Arrivals and Departures per Hour", 6, 45)],
        [(o_delay_hr, "Average Delay by Hour", 6, 45), (o_delay_wind, "Delay vs Wind", 6, 45)],
        [(o_weather_risk, "Weather Risk", 6, 38), (o_pipeline, "Pipeline Health", 6, 38)],
    ]
    operations_ids = [cid for row in operations_rows for cid, _, _, _ in row]

    dashboards = [
        (
            "Passenger Dashboard",
            "passenger-dashboard",
            passenger_rows,
            passenger_ids,
            10,
            [
                column_native_filter(
                    "Airport",
                    "airport_code",
                    [datasets["v_passenger_kpis"], datasets["v_passenger_flights"], datasets["v_weather_latest"]],
                    passenger_ids,
                    "NATIVE_FILTER-AIRPORT-passenger-dashboard",
                    multi_select=True,
                ),
                column_native_filter(
                    "Direction",
                    "direction",
                    [datasets["v_passenger_flights"]],
                    [p_fids, p_status_mix],
                    "NATIVE_FILTER-DIRECTION-passenger-dashboard",
                    multi_select=True,
                ),
            ],
        ),
        (
            "Airport Operations Dashboard",
            "airport-operations-dashboard",
            operations_rows,
            operations_ids,
            10,
            [
                column_native_filter(
                    "Airport",
                    "airport_code",
                    [
                        datasets["v_aircraft_now"],
                        datasets["v_hourly_ops"],
                        datasets["airport_metrics_5min"],
                        datasets["v_ops_current"],
                        datasets["v_delay_vs_weather"],
                    ],
                    [cid for cid in operations_ids if cid != o_pipeline],
                    "NATIVE_FILTER-AIRPORT-airport-operations-dashboard",
                    multi_select=True,
                ),
            ],
        ),
    ]

    existing_dashboards = session.get(
        f"{BASE}/api/v1/dashboard/?q=(page_size:100)",
        headers=headers,
        timeout=30,
    ).json()["result"]
    dashboards_by_slug = {item["slug"]: item["id"] for item in existing_dashboards if item.get("slug")}

    for title, slug, rows, chart_ids, refresh_seconds, native_filters in dashboards:
        metadata = {
            "refresh_frequency": refresh_seconds,
            "color_scheme": "supersetColors",
            "native_filter_configuration": native_filters,
        }
        body = {
            "dashboard_title": title,
            "published": True,
            "position_json": dashboard_position(rows),
            "json_metadata": json.dumps(metadata),
        }
        if slug in dashboards_by_slug:
            dashboard_id = dashboards_by_slug[slug]
            response = session.put(f"{BASE}/api/v1/dashboard/{dashboard_id}", headers=headers, json=body, timeout=30)
            response.raise_for_status()
            print(f"dashboard updated: {title} (id={dashboard_id})")
        else:
            body["slug"] = slug
            response = session.post(f"{BASE}/api/v1/dashboard/", headers=headers, json=body, timeout=30)
            response.raise_for_status()
            dashboard_id = response.json()["id"]
            print(f"dashboard created: {title} (id={dashboard_id})")

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
