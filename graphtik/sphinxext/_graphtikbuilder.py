# Copyright 2020, Kostis Anagnostopoulos.
# Licensed under the terms of the Apache License, Version 2.0. See the LICENSE file associated with the project for terms.
"""A builder that Render graphtik plots from doctest-runner's globals."""
from collections import OrderedDict
from hashlib import sha1
from pathlib import Path
from typing import Union

import pydot
from boltons.iterutils import first
from docutils import nodes
from sphinx.application import Sphinx
from sphinx.ext import doctest as extdoctest
from sphinx.locale import _, __
from sphinx.util import logging

from ..base import Plotter
from ..network import Solution
from . import doctestglobs, dynaimage, graphtik_node

Plottable = Union[None, Plotter, pydot.Dot]

log = logging.getLogger(__name__)

_image_mimetypes = {
    "svg": "image/svg+xml",
    "svgz": "image/svg+xml",
    "pdf": "image/x+pdf",
}


class HistoricDict(OrderedDict):
    def __setitem__(self, k, v):
        super().__setitem__(k, v)
        self.move_to_end(k)


class GraphtikPlotsBuilder(doctestglobs.ExposeGlobalsDocTestBuilder):
    """Retrieve *plottable* from doctests globals and render them. """

    run_empty_code = True

    def _make_group_globals(self, group: extdoctest.TestGroup):
        return HistoricDict()

    def _warn_out(self, text: str) -> None:
        """Silence warnings since urelated to building site. """
        log.info(f"WARN-like: {text}", nonl=True)
        self.outfile.write(text)

    def _globals_updated(self, code: extdoctest.TestCode, globs: dict):
        """Collect plottable from doctest-runner globals and render graphtik plot. """
        node: nodes.Node = code.node.parent

        if isinstance(node, graphtik_node):
            plottable = self._retrieve_graphvar_plottable(
                globs, node["graphvar"], (code.filename, code.lineno)
            )
            if plottable:
                dot: pydot.Dot = plottable if isinstance(
                    plottable, pydot.Dot
                ) else plottable.plot()
                img_format = node["img_format"]
                rel_img_path = self._render_dot_image(img_format, dot, node)
                dot_str = (
                    f"{plottable.debugstr()}"
                    if isinstance(plottable, Solution)
                    else plottable
                )
                self._upd_image_node(
                    node, rel_img_path, dot_str=str(dot_str), cmap_id=dot.get_name()
                )

    def _is_plottable(self, value):
        return isinstance(value, (Plotter, pydot.Dot))

    def _retrieve_graphvar_plottable(
        self, globs: dict, graphvar, location,
    ) -> Plottable:
        plottable: Plottable = None

        if graphvar is None:
            ## Pick last plottable from globals.
            #
            for i, var in enumerate(reversed(list(globs))):
                value = globs[var]
                if self._is_plottable(value):
                    log.debug(
                        __(
                            "picked plottable %r from doctest globals (num %s from the end0)"
                        ),
                        var,
                        i,
                        location=location,
                    )
                    plottable = value
                    break
            else:
                log.error(
                    __("could not find any plottable in doctest globals"),
                    location=location,
                )

        else:
            ## Pick named var from globals.
            #
            try:
                value = globs[graphvar]
                if not self._is_plottable(value):
                    log.warning(
                        __(
                            "value of graphvar %r in doctest globals is not plottable but %r"
                        ),
                        graphvar,
                        type(value).__name__,
                        location=location,
                    )
                else:
                    plottable = value
            except KeyError:
                log.warning(
                    __("could not find graphvar %r in doctest globals"),
                    graphvar,
                    location=location,
                )

        return plottable

    def _render_dot_image(
        self, img_format, dot: pydot.Dot, node: graphtik_node
    ) -> Path:
        """
        Ensure png(+usemap)|svg|svgz|pdf file exist, and return its path.
        """
        ## Derrive image-filename from graph contents.
        #
        hasher = sha1()
        hasher.update(str(dot).encode())
        fname = f"graphtik-{hasher.hexdigest()}.{img_format}"
        abs_fpath = Path(self.outdir, self.imagedir, fname)

        ## Don not re-write images, thay have content-named path,
        #  so they are never out-of-date.
        #
        if not abs_fpath.is_file():
            abs_fpath.parent.mkdir(parents=True, exist_ok=True)
            dot.write(abs_fpath, format=img_format)
            if img_format == "png":
                cmap = dot.create(format="cmapx", encoding="utf-8").decode("utf-8")
                node.cmap = cmap

        ## XXX: used to work till active-builder attributes were transfered to self.
        # rel_fpath = Path(self.imgpath, fname)
        rel_fpath = Path(self.imagedir, fname)

        return rel_fpath

    def _upd_image_node(
        self, node: graphtik_node, rel_img_path: Path, dot_str: str, cmap_id: str
    ):
        img_format: str = node["img_format"]
        assert img_format, (img_format, node)

        image_node: dynaimage = first(node.traverse(dynaimage))
        if img_format == "png":
            image_node.tag = "img"
            image_node["src"] = str(rel_img_path)
            image_node["usemap"] = f"#{cmap_id}"
            # HACK: graphtik-node not given to html-visitor.
            image_node.cmap = getattr(node, "cmap", "")
        else:
            image_node.tag = "object"
            # TODO: make sphinx-SVGs zoomable.
            image_node["data"] = str(rel_img_path)
            image_node["type"] = _image_mimetypes[img_format]

        if "alt" not in image_node:
            image_node["alt"] = dot_str


def get_graphtik_builder(app: Sphinx) -> GraphtikPlotsBuilder:
    """Initialize a singleton patched doctest-builder"""
    builder = getattr(app, "graphtik_builder", None)
    if builder is None:
        builder = GraphtikPlotsBuilder(app)
        builder.set_environment(app.env)
        builder.imgpath = app.builder.imgpath
        builder.imagedir = app.builder.imagedir
        builder.init()
        app.graphtik_builder = builder

    return builder