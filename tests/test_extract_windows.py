"""Pruebas de detección de índices no finitos sin acceso a S3."""

import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import warnings

import numpy as np
import pandas as pd
import xarray as xr

from tools.ac import extract_windows as windows


class IndicesNoFinitosTests(unittest.TestCase):
    def producto(self):
        shape = (5, 5)
        ds = xr.Dataset({
            b: (("y", "x"), np.full(shape, 0.01)) for b in windows.band_names
        })
        ds["lat"] = (("y", "x"), np.full(shape, -34.0))
        ds["lon"] = (("y", "x"), np.full(shape, -56.0))
        ds["l2_flags"] = (("y", "x"), np.zeros(shape, dtype=int))
        return ds

    def extraer_csv(self, ds, paths=None):
        puntos = pd.DataFrame({"pass_id": ["scene"], "lat": [-34.0], "lon": [-56.0]})
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "result.csv"
            argv = ["extract_windows", "--matchups", "unused.geojson", "--out", str(out)]
            with (
                patch("sys.argv", argv),
                patch.object(windows, "load_matchups", return_value=puntos),
                patch.object(windows, "get_s3_client", return_value=None),
                patch.object(windows, "download_pass_id_files", return_value=[Path("scene.nc")] if paths is None else paths),
                patch.object(windows, "open_l2w", return_value=ds),
                contextlib.redirect_stdout(io.StringIO()),
                warnings.catch_warnings(),
            ):
                warnings.simplefilter("ignore", RuntimeWarning)
                windows.main()
            return pd.read_csv(out).iloc[0]

    def test_indices_finitos(self):
        row = self.extraer_csv(self.producto())
        self.assertFalse(row.indices_no_finitos)
        self.assertAlmostEqual(row.ndci_mean, 0.0)
        self.assertAlmostEqual(row.combinado_mean, 0.02)

    def test_infinito_se_marca_y_se_conserva(self):
        ds = self.producto()
        ds["B02"].values[2, 2] = 0.0
        row = self.extraer_csv(ds)
        self.assertTrue(row.indices_no_finitos)
        self.assertTrue(np.isposinf(row.combinado_mean))
        self.assertTrue(np.isfinite(row.combinado_median))
        self.assertFalse(row.pocos_pixeles_buenos)

    def test_infinito_negativo(self):
        ds = self.producto()
        ds["B02"].values[:] = 0.0
        ds["B05"].values[:] = -0.01
        row = self.extraer_csv(ds)
        self.assertTrue(row.indices_no_finitos)
        self.assertTrue(np.isneginf(row.combinado_mean))

    def test_cero_sobre_cero(self):
        ds = self.producto()
        ds["B04"].values[:] = 0.0
        ds["B05"].values[:] = 0.0
        row = self.extraer_csv(ds)
        self.assertTrue(row.indices_no_finitos)
        self.assertTrue(pd.isna(row.ndci_mean))

    def test_pixel_excluido_no_marca_la_fila(self):
        ds = self.producto()
        ds["B02"].values[2, 2] = 0.0
        ds["l2_flags"].values[2, 2] = 2
        row = self.extraer_csv(ds)
        self.assertFalse(row.indices_no_finitos)
        self.assertAlmostEqual(row.combinado_mean, 0.02)

    def test_no_calculados_no_se_marcan(self):
        for sin_producto in (False, True):
            with self.subTest(sin_producto=sin_producto):
                ds = self.producto()
                ds["l2_flags"].values[:] = 2
                row = self.extraer_csv(ds, paths=[] if sin_producto else None)
                self.assertFalse(row.indices_no_finitos)
                self.assertTrue(row.sin_resultado if sin_producto else row.pocos_pixeles_buenos)


if __name__ == "__main__":
    unittest.main()
