"""Visualizaciones de diagnóstico de ACOLITE, sin descargas ni rutas de datos fijas."""

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import ListedColormap
from matplotlib.patches import Rectangle

BITS = {1: "NO_AGUA", 2: "CIRRUS", 4: "MUY_BRILLANTE", 8: "REFL_NEGATIVA", 16: "FUERA_ESCENA", 32: "MIXTO", 64: "SOMBRA"}


def banda(dl, prefijo, nm):
    # S2A/S2B/S2C tienen longitudes de onda centrales distintas: se toma la <prefijo>_<nm> mas cercana
    cands = [v for v in dl.data_vars if v.startswith(prefijo + "_")]
    return dl[min(cands, key=lambda v: abs(int(v.split("_")[1]) - nm))].values


def color_natural(dl):
    rgb = np.dstack([banda(dl, "rhot", 665), banda(dl, "rhot", 560), banda(dl, "rhot", 492)])
    lo, hi = np.nanpercentile(rgb, [2, 98])
    return np.clip((rgb - lo) / (hi - lo), 0, 1)


def pixel_mas_cercano(dl, lat, lon):
    d2 = (dl["lat"].values - lat) ** 2 + ((dl["lon"].values - lon) * np.cos(np.radians(lat))) ** 2
    return np.unravel_index(np.nanargmin(d2), d2.shape), float(np.sqrt(d2.min()) * 111_320)


def visualizar_ventana(r, w, i, j, *, causa="", idx="", pass_id="", grupo_nombre="",
                       radio=60, half=2, longitud_onda=1614, percentil=98, mostrar=True):
    """Muestra RGB, flags y una banda alrededor de un píxel de un par L2R/L2W.

    Los productos deben compartir grilla y recorte. `half` define la ventana
    marcada; `radio` define el contexto. Devuelve (figura, ejes).
    """
    R = radio
    p = {"pass_id": pass_id, "grupo_nombre": grupo_nombre}
    fl = w["l2_flags"].values.astype(int)
    sl = (slice(max(i - R, 0), i + R + 1), slice(max(j - R, 0), j + R + 1))
    i0, j0 = sl[0].start, sl[1].start
    ventana = fl[max(i - half, 0):i + half + 1, max(j - half, 0):j + half + 1]
    bits = {n: int(((ventana & b) > 0).sum()) for b, n in BITS.items() if ((ventana & b) > 0).any()}
    print(f"[{causa}] matchup {idx}  {p['pass_id']}  grupo {p['grupo_nombre']}")
    print(f"   flags en la ventana (pixeles de {ventana.size}): {bits}   buenos: {int((ventana == 0).sum())}")

    fig, axs = plt.subplots(1, 3, figsize=(17, 6))
    axs[0].imshow(color_natural(r)[sl])
    axs[0].set_title("color natural (rhot)")

    # un color por flag dominante en cada pixel (bit mas bajo prendido); 0 = bueno
    clase = np.zeros(fl.shape)
    for b in [64, 32, 16, 8, 4, 2, 1]:
        clase[(fl & b) > 0] = np.log2(b) + 1
    im = axs[1].imshow(clase[sl], cmap="tab10", vmin=0, vmax=9, interpolation="nearest")
    axs[1].set_title("l2_flags (bit mas bajo): 0 bueno, 1 NO_AGUA, 2 CIRRUS, 3 MUY_BRILL., 5 FUERA_ESC.")
    c = banda(r, "rhot", longitud_onda)
    im2 = axs[2].imshow(c[sl], cmap="viridis", vmin=0, vmax=np.nanpercentile(c[sl], percentil))
    plt.colorbar(im2, ax=axs[2], fraction=0.046)
    axs[2].set_title(f"rhot_{longitud_onda}")
    for ax in axs:
        ax.add_patch(Rectangle((j - j0 - half - 0.5, i - i0 - half - 0.5), 2 * half + 1, 2 * half + 1, fill=False, ec="red", lw=1.5))
        ax.axis("off")
    fig.suptitle(f"{causa}: matchup {idx}  {p['pass_id']}")
    plt.tight_layout()
    if mostrar:
        plt.show()
    return fig, axs


def visualizar_cirrus(dl, w, pts, *, titulo="", pass_id="", mostrar=True):
    """Muestra RGB, banda de cirrus y clases de flags para una escena.

    `pts` contiene lat/lon de los puntos a marcar. L2R y L2W deben compartir
    grilla y recorte. Devuelve (figura, ejes).
    """
    fl = w["l2_flags"].values.astype(int)
    cmap_flags = ListedColormap(["#2b7bba", "#f2f2f2", "#e8a33d", "#555555"])
    cirrus = (fl & 2) > 0
    brillante = (fl & 4) > 0
    bueno = fl == 0

    print(titulo, pass_id)
    print(f"  buenos {bueno.mean():.1%}   cirrus {cirrus.mean():.1%}   muy brillante {brillante.mean():.1%}   cirrus sin muy brillante {(cirrus & ~brillante).mean():.1%}")
    c = banda(dl, "rhot", 1373)
    print(f"  rhot_1373: mediana con cirrus {np.nanmedian(c[cirrus]):.3f}  /  sin cirrus {np.nanmedian(c[~cirrus]):.3f}")

    # 0 bueno, 1 solo cirrus, 2 cirrus + muy brillante, 3 otra cosa
    clase = np.full(fl.shape, 3)
    clase[bueno] = 0
    clase[cirrus & ~brillante] = 1
    clase[cirrus & brillante] = 2

    fig, axs = plt.subplots(1, 3, figsize=(16, 6))
    axs[0].imshow(color_natural(dl))
    axs[0].set_title("color natural (rhot B04-B03-B02)")
    im = axs[1].imshow(c, cmap="magma", vmin=0, vmax=np.nanpercentile(c, 99))
    axs[1].set_title("rhot_1373 (banda de cirrus)")
    plt.colorbar(im, ax=axs[1], fraction=0.046)
    axs[2].imshow(clase, cmap=cmap_flags, vmin=0, vmax=3, interpolation="nearest")
    axs[2].set_title("l2_flags: 0 bueno | 1 cirrus | 2 cirrus+brillante | 3 otro")
    for ax in axs:
        for _, p in pts.iterrows():
            (i, j), dist = pixel_mas_cercano(dl, p["lat"], p["lon"])
            if dist < 30:
                ax.plot(j, i, "c+", ms=10)
        ax.axis("off")
    fig.suptitle(f"{titulo}\n{pass_id}")
    plt.tight_layout()
    if mostrar:
        plt.show()
    return fig, axs
