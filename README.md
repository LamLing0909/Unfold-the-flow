# Unfold the flow

An interactive, JSON-driven flowchart with expandable nested nodes, directional layouts, and cycle support. The diagram runs in Python in the browser through PyScript and Pyodide.

**Author:** M.N Ling — [lamling0909@gmail.com](mailto:lamling0909@gmail.com)

This project was developed with AI assistance.

## License

The project is available under the [Unfold the flow Non-Commercial License](LICENSE). Non-commercial use is free. Commercial use, including internal business use by a for-profit organization, requires a separate paid written license in advance; contact [M.N Ling](mailto:lamling0909@gmail.com) to arrange one. Third-party materials are subject to their own terms.

Because it restricts commercial use, this license is not an OSI-approved open-source license.

## Getting started

Open `index.html` directly in a modern browser, including via `file://`. No local server is required. The page includes an example: edit its JSON and select **Draw chart**, or select **Load JSON** to open a local file.

**An internet connection is required:** PyScript, Pyodide, Pydantic, and the example image are loaded from the web. The standalone HTML embeds the application code and styles, but it is not a fully offline application. It uses PyScript's `py` (Pyodide) runtime, not `mpy`.

The example image is [Overhead desktop workspace](https://commons.wikimedia.org/wiki/File:Overhead_desktop_workspace_(Unsplash).jpg) by Jeff Sheldon, made available under CC0 on Wikimedia Commons. The image will not appear if the image host is unavailable.

> **Security:** Node `content` is rendered as HTML using `innerHTML`. Only load trusted JSON and HTML, or sanitize untrusted content before loading it.

## JSON format

See `sample.json` for a larger example with an image, `sample-basic.json` for a smaller example, and `sample-cycle.json` for an A → B → C → A cycle. Nodes are defined once and referenced by ID in `to`. Nest children directly; no flattened list is required.

```json
{
  "direction": "TB",
  "nodes": [
    {"id": "start", "content": "<strong>Start</strong>", "to": {"review": "Next"}},
    {"id": "review", "content": "<strong>Review</strong>", "unfolded": false,
      "children": [
        {"id": "check", "content": "<strong>Check</strong>", "to": {"finish": "Done"}}
      ]},
    {"id": "finish", "content": "<strong>Finish</strong>"}
  ]
}
```

- `direction`: `TB` (top to bottom, default; `TD` is an alias), `BT` (bottom to top), `LR` (left to right), or `RL` (right to left).
- `id`: unique, non-empty string.
- `content`: node summary as HTML, visible whether the node is expanded or collapsed.
- `children`: nested node array. Expanding a parent enlarges it to contain its children.
- `to`: object mapping target IDs to string labels, in edge order. Targets must exist.
- `unfolded`: initial expanded state; defaults to `false`.

For horizontal layouts, spacing accounts for currently visible edge labels, including projected child labels. Long labels can make a chart wider; pan or zoom to navigate.

## Layout, cycles and collapsed nodes

At each containment level, dependencies determine layers. Nodes without an ordering dependency can share a layer: side by side in vertical layouts or stacked in horizontal layouts. In acyclic portions, sources precede targets. For cycles and projected cross-group dependencies, first depth-first visit order identifies return edges; the remaining dependencies determine layers. Traversal starts with nodes without incoming edges, then processes remaining nodes in input order, following `to` order. Nodes are not drawn twice. Each containment level is laid out separately so parents continue to contain children. Parent–child and self-links cannot force two enclosing boxes into non-overlapping forward positions.

When a node is collapsed, edges between hidden descendants and external nodes temporarily attach to the nearest visible ancestor. Edges with both endpoints hidden under the same collapsed node are hidden. Projected labels are prefixed with `Child: `, or shown as `Child` if the original label is empty. Edges with identical visible endpoints are combined while preserving distinct labels. Expanding restores the actual endpoints and each child's previous expanded state. Ports and labels are separated where possible, though complex graphs can still have crossings.

### Node order

The source JSON string or input dictionary is not changed. The model maintains:

- `diagram.nodes`: top-level nodes in layout order.
- `node.children`: direct children in layout order.
- `diagram.nodes_flat`: all nodes, including hidden ones, in original depth-first containment order (parent first). Layout and expansion do not reorder this list.

```python
from diagram import Diagram

data = {"nodes": [
    {"id": "B"},
    {"id": "A", "to": {"B": "Next"}},
]}
d = Diagram.model_validate(data)
print([n.id for n in d.nodes])       # ['A', 'B']: layout order
print([n.id for n in d.nodes_flat])  # ['B', 'A']: input traversal order
```

## Python API

`diagram.py` depends on Pydantic 2. `Diagram` and `Node` are Pydantic models. `Diagram.model_validate_json()` validates the whole JSON document, including nested children and ID-based edges; use `Diagram.model_validate()` for a Python dictionary. After validation, the diagram builds its indexes, resolves edge IDs to nodes, checks duplicate IDs and missing targets, and calculates layout.

```python
from diagram import Diagram

d = Diagram.model_validate_json(json_string)  # Or Diagram.model_validate(data)
n = d.get('review')
print(n.parents)          # Ancestors, nearest first
print(n.from_)            # Nodes with edges to n
print(n.edge_ids)         # JSON target IDs -> labels
print(n.to)               # Resolved Node objects -> labels
print(n.unfolded, n.drew)
print(d.nodes, d.nodes_flat, d.rendered_ids)
d.mount('diagram')        # Bind to the DOM and render
d.toggle('review')
d.focus('approved')       # Reveal ancestors, zoom and center the node
d.set_zoom(1.5)
d.render()
d.destroy()
```

Nodes use identity-based equality and hashing. `from_` is used because `from` is a Python keyword; `getattr(n, 'from')` is also available. `diagram = Diagram` is provided as a lowercase alias. `drew` indicates whether a node was visible in the most recent render.

For asset mappings, pass `context={"assets": assets}` to `Diagram.model_validate_json()`. The previous `Diagram(json_string)` and `Diagram(data)` constructor forms have been replaced by the Pydantic methods above.

### Updating data

A `Diagram` represents one loaded JSON snapshot. `Node` and `Diagram` fields are public, but **callers are responsible for consistency**: modifying IDs, children, edge IDs, resolved edges, or node lists does not automatically revalidate, relink, rebuild indexes, or recompute layout. Setting `zoom` directly does not update the canvas; use `set_zoom()`. To update the full graph consistently, validate updated JSON and create a new diagram:

```python
# d is currently mounted; new_json contains the updated data.
new_diagram = Diagram.model_validate_json(new_json)  # Invalid input leaves d usable
d.destroy()                                        # Remove old listeners
d = new_diagram.mount('diagram')
```

Pass any assets again in the validation context. The new diagram takes its expanded state from the new JSON, not from the previous diagram. `toggle()` and `focus()` change display state; `render()` redraws the current model without reparsing JSON. The demo creates a new model when loading or redrawing JSON.

Pydantic validates nested structures recursively, and its JSON parser has a depth limit. Deeply nested documents can therefore fail validation; practical limits depend on the Pydantic version, structure, memory, and rendering performance. Tests cover 60 nested nodes. For multiple diagrams, use a distinct SVG arrow-marker ID per diagram.

## Navigation and focus

On mobile, drag within the canvas to pan and pinch to zoom. The **−** and **+** buttons adjust zoom; the percentage button resets it to 100%. Keyboard users can focus the canvas and scroll with arrow keys. Zoom is limited to 25–400%. Drag outside the canvas to scroll the page.

Use `d.set_zoom(1.5)` for 150%, read `d.zoom`, and optionally set `d.on_zoom` to a callback accepting the new scale. Zoom does not change JSON or expansion state; a newly loaded diagram starts at 100%.

Select **◎** or call `d.focus(node_id)` to expand the target's ancestors, fit the target to the viewport, and center it. The target's own expansion state is unchanged and other nodes remain visible. When focusing an expanded parent, visible internal edges and their labels are included in the fit, including loops extending outside the parent; external edges are not. An already visible target is not rebuilt. Zoom limits may prevent a very large or small target from fitting exactly. If an image changes size after focusing, edges redraw automatically; focus again to refit the view.

Flow alignment follows the selected direction: `TB` starts at top center, `BT` at bottom center, `LR` at center left, and `RL` at center right. Individual edge ports may be offset to reduce overlap.

## Node size changes

After mounting, `ResizeObserver` observes only visible nodes within that diagram's canvas. When an image loads or content changes a node's size, SVG edges are remeasured and redrawn on the next animation frame without rebuilding node HTML. Multiple changes are coalesced; expansion updates the observed elements, and `destroy()` disconnects the observer and cancels pending redraws. Canvas zoom is a visual transformation and does not change layout dimensions; measurements account for the scale. A browser supporting `ResizeObserver` is required.

## Development and build

`index.html` is generated: edit the sources rather than the generated file.

- `diagram.py`: reusable flowchart module.
- `app.py`: demo JSON loading and interactions.
- `style.css`: page and diagram styles.
- `index.template.html`: page structure and build markers.
- `build.py`: produces the single-file HTML.

```sh
python build.py          # Generate index.html
python build.py --check  # Exit non-zero if index.html is stale
```

The build uses only Python's standard library; Node and a server are not required. It embeds both Python files into one PyScript block, so the standalone page does not depend on `file://` module imports. For separate-module use, configure PyScript file mapping; browser security rules can block local module loading under `file://`.

Internally, `render()` builds the canvas and visible nodes. `_draw_lines()` coordinates measurement (`_measure_nodes`), collapsed-edge projection (`_project_edges`), routing (`_route_edges`), and SVG creation (`_paint_svg`). Size changes only redraw the edges. These are implementation details rather than public API.

## Tests

```sh
python -m pip install "pydantic>=2.12,<3"
python -m unittest discover -s tests -v
```

Optional browser integration tests require Node.js, Playwright, Chromium, and internet access to the PyScript CDN:

```sh
node tests/test_browser.cjs
node tests/test_focus_edges.cjs
node tests/test_pydantic_browser.cjs
```

They check example edge labels, focused internal loops, and in-browser Pydantic validation respectively. Set `CHROMIUM_PATH` if necessary to point to a Chromium executable.
