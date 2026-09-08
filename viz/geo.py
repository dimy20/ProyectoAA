import geopandas as gpd
import folium
import sys

def _is_notebook():
    if 'IPython' not in sys.modules:
        return False
    from IPython import get_ipython
    return get_ipython().__class__.__name__ == 'ZMQInteractiveShell'

def show_cluster(num: int, gdf: gpd.GeoDataFrame, cluster_key: str = "grupo"):
    m = gdf[gdf[cluster_key] == num].to_crs(4326).explore(
        column=cluster_key,
        categorical=True,
        cmap="tab20",
        tiles="Esri.WorldImagery",
        marker_kwds={"radius": 5},
        style_kwds={"fillOpacity": 0.8, "color": "white", "weight": 1},
        legend=False
    )

    if _is_notebook():
        return m

    out_path = "cluster_map.html"
    m.save(out_path)
    print(f"Map saved to {out_path}")

def show_selected_groups(gdf: gpd.GeoDataFrame, selected_groups: list, cluster_key: str = "grupo_final"):
    gdf = gdf.to_crs(4326)
    is_selected = gdf[cluster_key].isin(selected_groups)

    m = gdf[~is_selected].explore(
        color="lightgray",
        tiles="Esri.WorldImagery",
        marker_kwds={"radius": 4},
        style_kwds={"fillOpacity": 0.35, "color": "gray", "weight": 0.5},
        name="No seleccionados",
    )

    gdf[is_selected].explore(
        m=m,
        column=cluster_key,
        categorical=True,
        cmap="tab10",
        marker_kwds={"radius": 7},
        style_kwds={"fillOpacity": 0.9, "color": "black", "weight": 1},
        legend=True,
        name="Seleccionados",
    )

    folium.LayerControl(collapsed=False).add_to(m)

    if _is_notebook():
        return m

    out_path = "selected_groups_map.html"
    m.save(out_path)
    print(f"Map saved to {out_path}")

PAIR_COLORS = ["red", "blue", "green", "purple", "orange", "darkred", "cadetblue", "darkgreen", "pink", "gray"]

def show_nearest_stations(centroides: gpd.GeoSeries, stations_gdf: gpd.GeoDataFrame, station_name_col: str = "name"):
    stations = stations_gdf.to_crs(centroides.crs)
    centroides_4326 = centroides.to_crs(4326)
    stations_4326 = stations.to_crs(4326)

    m = folium.Map(tiles="Esri.WorldImagery")
    bounds = []

    for i, (group_name, point) in enumerate(centroides.items()):
        color = PAIR_COLORS[i % len(PAIR_COLORS)]

        dists = stations.distance(point)
        idx = dists.argmin()
        distance_km = dists.min() / 1000
        station_name = stations.iloc[idx][station_name_col]

        centroid_latlon = (centroides_4326.loc[group_name].y, centroides_4326.loc[group_name].x)
        station_point = stations_4326.iloc[idx].geometry
        station_latlon = (station_point.y, station_point.x)
        bounds.extend([centroid_latlon, station_latlon])

        folium.PolyLine(
            [centroid_latlon, station_latlon],
            color=color, weight=2, dash_array="5,5",
            tooltip=f"{group_name} -> {station_name} ({distance_km:.1f} km)",
        ).add_to(m)

        folium.CircleMarker(
            centroid_latlon, radius=7, color=color, fill=True, fill_opacity=0.9,
            popup=f"Centroide: {group_name}",
            tooltip=f"Centroide {group_name}",
        ).add_to(m)

        folium.Marker(
            station_latlon,
            icon=folium.Icon(color=color, icon="cloud"),
            popup=f"Estacion mas cercana a {group_name}: {station_name} ({distance_km:.1f} km)",
            tooltip=station_name,
        ).add_to(m)

    m.fit_bounds(bounds)

    if _is_notebook():
        return m

    out_path = "nearest_stations_map.html"
    m.save(out_path)
    print(f"Map saved to {out_path}")