"""Pruebas del contrato de CRS y cierre del runner, sin servicios externos."""

import contextlib
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point

from tools.ac import run_acolite as runner


PASS_ID = "S2A_MSIL1C_20220101T135111_N0500_R024_T21HUD_20230102T000000"


class MatchupsCRSTests(unittest.TestCase):
    def test_utm21s_preserva_coordenadas_metricas(self):
        gdf = gpd.GeoDataFrame({"pass_id": [PASS_ID]}, geometry=[Point(500000, 6200000)], crs=32721)
        with patch.object(runner.gpd, "read_file", return_value=gdf):
            result = runner.load_matchups(Path("matchups.geojson"))
        expected = gdf.to_crs(4326)
        np.testing.assert_allclose(result.lon, expected.geometry.x)
        np.testing.assert_allclose(result.lat, expected.geometry.y)
        self.assertEqual(result.x.iloc[0], 500000)
        self.assertEqual(result.y.iloc[0], 6200000)
        self.assertEqual(result.key.iloc[0], runner.scene_key(PASS_ID))

    def test_rechaza_otro_crs_o_crs_ausente(self):
        for crs in (4326, 32722, None):
            with self.subTest(crs=crs):
                gdf = gpd.GeoDataFrame({"pass_id": [PASS_ID]}, geometry=[Point(0, 0)], crs=crs)
                with patch.object(runner.gpd, "read_file", return_value=gdf):
                    with self.assertRaisesRegex(ValueError, "expected CRS EPSG:32721"):
                        runner.load_matchups(Path("matchups.geojson"))


class RunnerCierreTests(unittest.TestCase):
    def test_offline_cierra_y_respeta_no_upload(self):
        for no_upload in (False, True):
            with self.subTest(no_upload=no_upload), tempfile.TemporaryDirectory() as td:
                args = SimpleNamespace(
                    no_upload=no_upload, scenes=Path("unused.csv"), matchups=Path("unused.geojson"),
                    only=None, limit=None, workdir=Path(td), prefix="test", bucket="test",
                )
                scenes = pd.DataFrame({"name": [PASS_ID + ".SAFE"], "id": ["id"], "online": [False]})
                points = pd.DataFrame({"pass_id": [PASS_ID], "key": [runner.scene_key(PASS_ID)]})
                output = io.StringIO()
                with (
                    patch.object(runner, "parse_args", return_value=args),
                    patch.object(runner, "load_acolite_params", return_value=({}, 0.05)),
                    patch.object(runner, "get_s3_client", return_value=Mock()),
                    patch.object(runner.pd, "read_csv", return_value=scenes),
                    patch.object(runner, "load_matchups", return_value=points),
                    patch.object(runner, "segment_slice", return_value=slice(None)),
                    patch.object(runner, "process_scene") as process,
                    patch.object(runner, "_maybe_terminate_pod") as terminate,
                    contextlib.redirect_stdout(output),
                ):
                    with self.assertRaises(SystemExit) as exit_result:
                        runner.main()
                self.assertEqual(exit_result.exception.code, 1)
                self.assertIn("(no reason recorded)", output.getvalue())
                process.assert_not_called()
                self.assertEqual(terminate.call_count, 0 if no_upload else 1)


if __name__ == "__main__":
    unittest.main()
