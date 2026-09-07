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