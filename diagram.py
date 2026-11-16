"""JSON-driven expandable diagram for PyScript with Pyodide (py)."""
import math
import unicodedata
from collections import OrderedDict
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

_text_measure_context = None


class Node(BaseModel):
    """JSON node and drawing node; edge IDs are resolved after validation."""
    model_config = ConfigDict(strict=True)

    id: str
    content: str = ''
    unfolded: bool = False
    children: list['Node'] = Field(default_factory=list, repr=False)
    edge_ids: dict[str, str] = Field(default_factory=dict, alias='to', repr=False)
    drew: bool = Field(default=False, exclude=True)
    # Runtime fields are public; JSON's "to" is validated by edge_ids.
    # A separate validation alias keeps the resolved Node keys out of JSON input.
    to: OrderedDict['Node', str] = Field(default_factory=OrderedDict, validation_alias='__resolved_to__', exclude=True, repr=False)
    diagram: Any = Field(default=None, exclude=True, repr=False)
    _parent: Any = None

    # Nodes are graph keys: equality and hash must not change when fields change.
    __eq__ = object.__eq__
    __hash__ = object.__hash__

    @field_validator('id')
    @classmethod
    def nonempty_id(cls, value):
        if not value.strip():
            raise ValueError('Each node must have a non-empty string id.')
        return value

    @property
    def parents(self):
        """Containment ancestors, nearest first."""
        out, current = [], self._parent
        while current is not None:
            out.append(current)
            current = current._parent
        return out

    @property
    def from_(self):
        """Nodes with an outgoing edge to this node, in source order."""
        return [n for n in self.diagram.nodes_flat if self in n.to] if self.diagram else []


class Diagram(BaseModel):
    """Validate a JSON snapshot, then link its nodes for drawing.

    Use model_validate_json for JSON text and model_validate for a Python dict.
    Graph fields are public; changing them does not rebuild indexes or layout.
    """
    model_config = ConfigDict(strict=True)

    nodes: list[Node]
    direction: Literal['TB', 'BT', 'LR', 'RL'] = 'TB'
    # Public runtime state is excluded from JSON output; changes are not
    # automatically reconciled with the graph or the rendered view.
    nodes_flat: list[Node] = Field(default_factory=list, exclude=True, repr=False)
    rendered_ids: set[str] = Field(default_factory=set, exclude=True, repr=False)
    on_zoom: Any = Field(default=None, exclude=True, repr=False)
    assets: Any = Field(default_factory=dict, exclude=True, repr=False)
    zoom: float = Field(default=1.0, exclude=True)

    # Pydantic recognises leading-underscore attributes as private and copies
    # mutable defaults for each model instance.
    _by_id: dict = {}
    _layers: dict = {}
    _cards: dict = {}
    _container: Any = None
    _click_proxy: Any = None
    _resize_observer: Any = None
    _resize_proxy: Any = None
    _frame_proxy: Any = None
    _frame_id: Any = None
    _canvas: Any = None
    _lines: Any = None
    _edge_elements: list = []
    _stage: Any = None
    _pad_x: float = 0.0
    _pad_y: float = 0.0
    _touch_proxies: dict = {}
    _touch_state: Any = None

    @field_validator('direction', mode='before')
    @classmethod
    def normalize_direction(cls, value):
        return 'TB' if value == 'TD' else value

    @model_validator(mode='after')
    def link_graph(self, info: ValidationInfo):
        """Build indexes and connect validated ID references to Node objects."""
        self.assets = (info.context or {}).get('assets', {})
        self.nodes_flat = []
        self.rendered_ids = set()
        self.on_zoom = None
        self.zoom = 1.0
        self._by_id = {}
        stack = [(node, None) for node in reversed(self.nodes)]
        while stack:
            node, parent = stack.pop()
            if node.id in self._by_id:
                raise ValueError('Duplicate node id: ' + node.id)
            node.diagram = self
            node._parent = parent
            node.to = OrderedDict()
            self.nodes_flat.append(node)
            self._by_id[node.id] = node
            stack.extend((child, node) for child in reversed(node.children))
        for source in self.nodes_flat:
            for target_id, label in source.edge_ids.items():
                target = self._by_id.get(target_id)
                if target is None:
                    raise ValueError('Node ' + source.id + ' references a nonexistent node: ' + target_id)
                source.to[target] = label
        self._order_nodes()
        return self

    def _order_nodes(self):
        """Compute layout layers and reorder each sibling list in place.

        self.nodes and every node.children become layout order; nodes_flat
        remains the original JSON containment traversal (parent before child).
        The input JSON or dict is not modified. Edges crossing containment
        groups are projected to siblings; cycles use first DFS visit order.
        """
        self._layers = {}
        groups = {None: self.nodes}
        for n in self.nodes_flat:
            groups[n] = n.children
        deps = {parent: [] for parent in groups}
        def chain(node):
            out = []
            while node is not None:
                out.append(node)
                node = node._parent
            out.reverse()
            return out
        chains = {node: chain(node) for node in self.nodes_flat}
        for source in self.nodes_flat:
            for target in source.to:
                left, right = chains[source], chains[target]
                i = 0
                while i < len(left) and i < len(right) and left[i] is right[i]:
                    i += 1
                # Ancestor/descendant/self links are drawn but cannot order
                # two enclosing boxes relative to one another.
                if i == len(left) or i == len(right):
                    continue
                parent = left[i-1] if i else None
                pair = (left[i], right[i])
                if pair not in deps[parent]:
                    deps[parent].append(pair)
        for parent, items in groups.items():
            if len(items) < 2:
                for node in items:
                    self._layers[node] = 0
                continue
            outgoing = {node: [] for node in items}
            reverse = {node: [] for node in items}
            for left, right in deps[parent]:
                outgoing[left].append(right)
                reverse[right].append(left)
            # First visit sources, then remaining cycles, in input order.
            starts = [n for n in items if not reverse[n]] + list(items)
            seen, rank, finish = set(), {}, []
            for node in starts:
                if node in seen:
                    continue
                stack = [(node, False)]
                while stack:
                    current, exiting = stack.pop()
                    if exiting:
                        finish.append(current)
                        continue
                    if current in seen:
                        continue
                    seen.add(current)
                    rank[current] = len(rank)
                    stack.append((current, True))
                    for nxt in reversed(outgoing[current]):
                        if nxt not in seen:
                            stack.append((nxt, False))
            # Strongly connected components; each cycle follows DFS visit order.
            assigned, components, component_of = set(), [], {}
            for node in reversed(finish):
                if node in assigned:
                    continue
                comp, stack = [], [node]
                assigned.add(node)
                while stack:
                    current = stack.pop()
                    comp.append(current)
                    for nxt in reverse[current]:
                        if nxt not in assigned:
                            assigned.add(nxt)
                            stack.append(nxt)
                comp.sort(key=lambda n: rank[n])
                index = len(components)
                for n in comp:
                    component_of[n] = index
                components.append(comp)
            adj = {i: [] for i in range(len(components))}
            indegree = {i: 0 for i in range(len(components))}
            for left, right in deps[parent]:
                x, y = component_of[left], component_of[right]
                if x != y and y not in adj[x]:
                    adj[x].append(y)
                    indegree[y] += 1
            pending = list(range(len(components)))
            component_layer = {i: 0 for i in pending}
            result = []
            while pending:
                ready = [i for i in pending if indegree[i] == 0]
                ready.sort(key=lambda i: min(rank[n] for n in components[i]))
                current = ready[0]
                pending.remove(current)
                comp = components[current]
                result.extend(comp)
                # Within a cycle, ignore edges returning to an earlier DFS
                # discovery for layering. Independent branches remain parallel.
                internal_layer = {node: 0 for node in comp}
                for node in comp:
                    for target in outgoing[node]:
                        if component_of[target] == current and rank[node] < rank[target]:
                            internal_layer[target] = max(internal_layer[target], internal_layer[node] + 1)
                for node in comp:
                    self._layers[node] = component_layer[current] + internal_layer[node]
                span = max(internal_layer.values()) + 1
                for nxt in adj[current]:
                    component_layer[nxt] = max(component_layer[nxt], component_layer[current] + span)
                    indegree[nxt] -= 1
            # items is self.nodes or a node.children list; nodes_flat is separate.
            items[:] = result

    def get(self, node_id):
        return self._by_id.get(node_id)

    def visible_nodes(self):
        """Return (node, depth); descendants remain hidden under closed ancestors."""
        out = []
        stack = [(node, 0) for node in reversed(self.nodes)]
        while stack:
            node, depth = stack.pop()
            out.append((node, depth))
            if node.unfolded:
                for child in reversed(node.children):
                    stack.append((child, depth + 1))
        return out

    def toggle(self, node_id):
        node = self.get(node_id)
        if node and node.children:
            node.unfolded = not node.unfolded
            if self._container is not None:
                self.render()

    def focus(self, node_id):
        """Reveal and center a node, zooming to fit within the viewport."""
        node = self.get(node_id)
        if node is None:
            raise ValueError('Node not found: ' + str(node_id))
        if self._container is None:
            raise ValueError('Call mount(element) first.')
        ancestors = node.parents
        needs_render = any(not ancestor.unfolded for ancestor in ancestors)
        for ancestor in ancestors:
            ancestor.unfolded = True
        if needs_render:
            self.render()
        viewport, canvas = self._container, self._canvas
        card = self._cards[node.id]
        card_rect, canvas_rect = card.getBoundingClientRect(), canvas.getBoundingClientRect()
        x = float(card_rect.left - canvas_rect.left) / self.zoom
        y = float(card_rect.top - canvas_rect.top) / self.zoom
        width = float(card_rect.width) / self.zoom
        height = float(card_rect.height) / self.zoom
        view_width, view_height = float(viewport.clientWidth), float(viewport.clientHeight)
        margin = 24.0
        center_x, center_y = x + width / 2, y + height / 2
        # Keep the selected card centered, but enlarge its fitting rectangle
        # symmetrically to include visible edges between its descendants. Paths
        # may leave a group, especially for back edges. External edges do not
        # affect focus. Labels are included as well as the SVG paths.
        left, top, right, bottom = x, y, x + width, y + height
        if node.unfolded:
            for source, target, path, text in self._edge_elements:
                if node not in source.parents or node not in target.parents:
                    continue
                for element in (path, text):
                    if element is None:
                        continue
                    r = element.getBoundingClientRect()
                    left = min(left, float(r.left - canvas_rect.left) / self.zoom)
                    top = min(top, float(r.top - canvas_rect.top) / self.zoom)
                    right = max(right, float(r.right - canvas_rect.left) / self.zoom)
                    bottom = max(bottom, float(r.bottom - canvas_rect.top) / self.zoom)
        fit_width = 2 * max(center_x - left, right - center_x)
        fit_height = 2 * max(center_y - top, bottom - center_y)
        fit = min(max(1.0, view_width - margin * 2) / max(fit_width, 1.0),
                  max(1.0, view_height - margin * 2) / max(fit_height, 1.0))
        # Scrollable padding lets even a first or last node reach the center.
        self._pad_x, self._pad_y = view_width / 2, view_height / 2
        self._apply_zoom()
        scale = self.set_zoom(fit)
        viewport.scrollLeft = self._pad_x + (x + width / 2) * scale - view_width / 2
        viewport.scrollTop = self._pad_y + (y + height / 2) * scale - view_height / 2
        return node

    def mount(self, element):
        """Mount once; element is an element id or a DOM element."""
        from pyscript import document, window
        from pyscript.ffi import create_proxy
        container = document.getElementById(element) if isinstance(element, str) else element
        if not container:
            raise ValueError('Diagram container not found.')
        self.destroy()
        self._container = container
        def click(event):
            button = event.target.closest('[data-flow-focus], [data-flow-toggle]')
            if button and self._container.contains(button):
                if button.hasAttribute('data-flow-focus'):
                    self.focus(button.getAttribute('data-flow-focus'))
                else:
                    self.toggle(button.getAttribute('data-flow-toggle'))
        self._click_proxy = create_proxy(click)
        self._resize_proxy = create_proxy(self._on_node_resize)
        self._frame_proxy = create_proxy(self._on_redraw_frame)
        self._resize_observer = window.ResizeObserver.new(self._resize_proxy)
        container.addEventListener('click', self._click_proxy)
        container.scrollLeft = 0
        container.scrollTop = 0
        # One finger pans inside the viewport; two fingers zoom around their midpoint.
        touch_options = window.Object.new()
        touch_options.passive = False
        for name, handler in (('touchstart', self._touch_start),
                              ('touchmove', self._touch_move),
                              ('touchend', self._touch_end),
                              ('touchcancel', self._touch_end)):
            proxy = create_proxy(handler)
            self._touch_proxies[name] = proxy
            container.addEventListener(name, proxy, touch_options)
        self.render()
        return self

    def set_zoom(self, scale, anchor_x=None, anchor_y=None):
        """Zoom within 25–400%, keeping a viewport point in place where possible."""
        scale = float(scale)
        if not math.isfinite(scale):
            raise ValueError('Zoom must be a finite number.')
        scale = max(0.25, min(4.0, scale))
        if self._container is None or self._stage is None:
            self.zoom = scale
        else:
            viewport = self._container
            ax = float(viewport.clientWidth) / 2 if anchor_x is None else float(anchor_x)
            ay = float(viewport.clientHeight) / 2 if anchor_y is None else float(anchor_y)
            world_x = (float(viewport.scrollLeft) + ax - self._pad_x) / self.zoom
            world_y = (float(viewport.scrollTop) + ay - self._pad_y) / self.zoom
            self.zoom = scale
            self._apply_zoom()
            viewport.scrollLeft = self._pad_x + world_x * scale - ax
            viewport.scrollTop = self._pad_y + world_y * scale - ay
        if self.on_zoom is not None:
            self.on_zoom(self.zoom)
        return self.zoom

    def _apply_zoom(self):
        """Scale canvas visually and size its scrollable stage to match."""
        if self._stage is None or self._canvas is None:
            return
        self._canvas.style.transform = 'scale(%s)' % self.zoom
        self._canvas.style.left = str(self._pad_x) + 'px'
        self._canvas.style.top = str(self._pad_y) + 'px'
        width = float(self._lines.getAttribute('width') or 0)
        height = float(self._lines.getAttribute('height') or 0)
        self._stage.style.width = str(width * self.zoom + 2 * self._pad_x) + 'px'
        self._stage.style.height = str(height * self.zoom + 2 * self._pad_y) + 'px'

    def _touch_start(self, event):
        touches = event.touches
        if touches.length == 1:
            touch = touches.item(0)
            self._touch_state = ('pan', float(touch.clientX), float(touch.clientY))
        elif touches.length >= 2:
            first, second = touches.item(0), touches.item(1)
            x1, y1 = float(first.clientX), float(first.clientY)
            x2, y2 = float(second.clientX), float(second.clientY)
            rect = self._container.getBoundingClientRect()
            mx = (x1 + x2) / 2 - float(rect.left) - float(self._container.clientLeft)
            my = (y1 + y2) / 2 - float(rect.top) - float(self._container.clientTop)
            distance = max(1.0, math.hypot(x2 - x1, y2 - y1))
            world_x = (float(self._container.scrollLeft) + mx - self._pad_x) / self.zoom
            world_y = (float(self._container.scrollTop) + my - self._pad_y) / self.zoom
            self._touch_state = ('pinch', distance, self.zoom, world_x, world_y)

    def _touch_move(self, event):
        touches, state = event.touches, self._touch_state
        if not state or not self._container:
            return
        if touches.length >= 2:
            if state[0] != 'pinch':
                self._touch_start(event)
                state = self._touch_state
            event.preventDefault()
            first, second = touches.item(0), touches.item(1)
            x1, y1 = float(first.clientX), float(first.clientY)
            x2, y2 = float(second.clientX), float(second.clientY)
            rect = self._container.getBoundingClientRect()
            mx = (x1 + x2) / 2 - float(rect.left) - float(self._container.clientLeft)
            my = (y1 + y2) / 2 - float(rect.top) - float(self._container.clientTop)
            distance = math.hypot(x2 - x1, y2 - y1)
            zoom = self.set_zoom(state[2] * distance / state[1], mx, my)
            self._container.scrollLeft = self._pad_x + state[3] * zoom - mx
            self._container.scrollTop = self._pad_y + state[4] * zoom - my
        elif touches.length == 1:
            if state[0] != 'pan':
                self._touch_start(event)
                return
            touch = touches.item(0)
            x, y = float(touch.clientX), float(touch.clientY)
            event.preventDefault()
            self._container.scrollLeft += state[1] - x
            self._container.scrollTop += state[2] - y
            self._touch_state = ('pan', x, y)

    def _touch_end(self, event):
        self._touch_state = None
        if event.touches.length:
            self._touch_start(event)

    def _stop_observing(self):
        """Disconnect old cards and cancel a queued redraw before replacing them."""
        if self._resize_observer is not None:
            self._resize_observer.disconnect()
        if self._frame_id is not None:
            from pyscript import window
            window.cancelAnimationFrame(self._frame_id)
            self._frame_id = None

    def _on_node_resize(self, entries, observer):
        # Several cards can resize in the same frame. Queue just one redraw.
        if self._container is not None and self._frame_id is None:
            from pyscript import window
            self._frame_id = window.requestAnimationFrame(self._frame_proxy)

    def _on_redraw_frame(self, timestamp):
        self._frame_id = None
        if self._container is not None and self._canvas is not None:
            self._draw_lines()

    def destroy(self):
        self._stop_observing()
        if self._container is not None:
            for name, proxy in self._touch_proxies.items():
                self._container.removeEventListener(name, proxy)
                proxy.destroy()
        self._touch_proxies = {}
        self._touch_state = None
        if self._container is not None and self._click_proxy is not None:
            self._container.removeEventListener('click', self._click_proxy)
            if hasattr(self._click_proxy, 'destroy'):
                self._click_proxy.destroy()
        for proxy in (self._resize_proxy, self._frame_proxy):
            if proxy is not None and hasattr(proxy, 'destroy'):
                proxy.destroy()
        self._resize_observer = None
        self._resize_proxy = None
        self._frame_proxy = None
        self._canvas = None
        self._lines = None
        self._edge_elements = []
        self._stage = None
        self._pad_x = 0.0
        self._pad_y = 0.0
        self._container = None
        self._click_proxy = None
        self.rendered_ids = set()
        for node in self.nodes_flat:
            node.drew = False

    def render(self):
        """Rebuild the visible nodes, then draw and observe their connections."""
        if self._container is None:
            raise ValueError('Call mount(element) first.')
        self._stop_observing()
        old_left, old_top = self._container.scrollLeft, self._container.scrollTop
        nodes_layer = self._create_canvas()
        self._build_nodes(nodes_layer)
        self._draw_lines()
        self._container.scrollLeft = old_left
        self._container.scrollTop = old_top
        # Only this diagram's visible cards are observed.
        for card in self._cards.values():
            self._resize_observer.observe(card)

    def _create_canvas(self):
        """Replace the diagram's DOM and return the host for its root nodes."""
        from pyscript import document
        container = self._container
        container.replaceChildren()
        stage = document.createElement('div')
        stage.className = 'flow-stage'
        container.appendChild(stage)
        canvas = document.createElement('div')
        canvas.className = 'flow-canvas'
        if self.direction in ('LR', 'RL'):
            canvas.classList.add('flow-horizontal')
        if self.direction == 'BT':
            canvas.classList.add('flow-reverse-tb')
        elif self.direction == 'RL':
            canvas.classList.add('flow-reverse-lr')
        stage.appendChild(canvas)
        self._stage = stage
        canvas.style.transform = 'scale(%s)' % self.zoom
        nodes_layer = document.createElement('div')
        nodes_layer.className = 'flow-roots'
        canvas.appendChild(nodes_layer)
        lines = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
        lines.setAttribute('class', 'flow-lines')
        lines.setAttribute('aria-hidden', 'true')
        canvas.appendChild(lines)
        self._canvas = canvas
        self._lines = lines
        return nodes_layer

    def _build_nodes(self, nodes_layer):
        """Build visible nested cards and record their DOM elements by node id."""
        from pyscript import document
        visible = self.visible_nodes()
        self.rendered_ids = set(node.id for node, depth in visible)
        if self.direction in ('LR', 'RL'):
            # Reserve horizontal space for the longest currently displayed label,
            # including labels projected from hidden children.
            edges = self._project_edges()
            gap = max([42] + [self._label_width(label) + 28 for _, _, label in edges if label])
            self._canvas.style.setProperty('--flow-direction-gap', str(gap) + 'px')
        self._cards = {}
        child_hosts = {}
        layer_hosts = {}
        for node in self.nodes_flat:
            node.drew = node.id in self.rendered_ids
        for node, depth in visible:
            parent_host = child_hosts[node._parent.id] if node._parent is not None else nodes_layer
            layer_key = (node._parent, self._layers[node])
            if layer_key not in layer_hosts:
                layer = document.createElement('div')
                layer.className = 'flow-layer'
                parent_host.appendChild(layer)
                layer_hosts[layer_key] = layer
            layer = layer_hosts[layer_key]
            card = document.createElement('div')
            card.className = 'flow-node is-open' if node.unfolded and node.children else 'flow-node'
            card.setAttribute('data-node-id', node.id)
            head = document.createElement('div')
            head.className = 'flow-head'
            content = document.createElement('div')
            content.className = 'flow-content'
            # content intentionally supports HTML. Only use trusted input.
            content.innerHTML = node.content
            image_nodes = content.querySelectorAll('img[data-asset]')
            for image_index in range(image_nodes.length):
                image = image_nodes.item(image_index)
                asset_name = image.getAttribute('data-asset')
                if asset_name in self.assets:
                    image.setAttribute('src', self.assets[asset_name])
            head.appendChild(content)
            focus_button = document.createElement('button')
            focus_button.type = 'button'
            focus_button.className = 'flow-focus'
            focus_button.setAttribute('data-flow-focus', node.id)
            focus_button.setAttribute('aria-label', 'Focus ' + node.id)
            focus_button.setAttribute('title', 'Focus node')
            focus_button.textContent = '◎'
            head.appendChild(focus_button)
            if node.children:
                button = document.createElement('button')
                button.type = 'button'
                button.className = 'flow-toggle'
                button.setAttribute('data-flow-toggle', node.id)
                button.setAttribute('aria-expanded', 'true' if node.unfolded else 'false')
                button.setAttribute('aria-label', ('Collapse ' if node.unfolded else 'Expand ') + node.id)
                button.textContent = ('−' if node.unfolded else '+') + '  ' + str(len(node.children))
                head.appendChild(button)
            card.appendChild(head)
            if node.unfolded and node.children:
                host = document.createElement('div')
                host.className = 'flow-children'
                card.appendChild(host)
                child_hosts[node.id] = host
            layer.appendChild(card)
            self._cards[node.id] = card

        if not visible:
            nodes_layer.textContent = 'No nodes yet.'

    def _draw_lines(self):
        """Measure, project, route, and paint without rebuilding node HTML."""
        visible = self.visible_nodes()
        bounds, layer_bounds, last_in_layer, right, bottom = self._measure_nodes(visible)
        edges = self._project_edges()
        # Route reverse directions in a mirrored coordinate system; paint paths
        # back in physical coordinates so the existing orthogonal router is reused.
        if self.direction == 'BT':
            bounds = {key: (x0, bottom-y1, x1, bottom-y0) for key, (x0, y0, x1, y1) in bounds.items()}
            layer_bounds = {key: (x0, bottom-y1, x1, bottom-y0) for key, (x0, y0, x1, y1) in layer_bounds.items()}
        elif self.direction == 'RL':
            bounds = {key: (right-x1, y0, right-x0, y1) for key, (x0, y0, x1, y1) in bounds.items()}
            layer_bounds = {key: (right-x1, y0, right-x0, y1) for key, (x0, y0, x1, y1) in layer_bounds.items()}
        routes = self._route_edges(visible, bounds, layer_bounds, last_in_layer, edges)
        max_label = max([len(label) for _, _, label in edges] + [0])
        width = max(500, right + 100 + len(edges) * 26 + max_label * 12)
        height = max(180, bottom + 100 + len(edges) * 26)
        self._paint_svg(width, height, routes, right, bottom, edges)

    def _measure_nodes(self, visible):
        """Return card/layer rectangles in canvas coordinates and drawing extents."""
        canvas = self._canvas
        rect = canvas.getBoundingClientRect()
        bounds = {}
        layer_bounds = {}
        right = 0
        bottom = 0
        last_in_layer = {}
        for node, depth in visible:
            card_rect = self._cards[node.id].getBoundingClientRect()
            x = float(card_rect.left - rect.left) / self.zoom
            y = float(card_rect.top - rect.top) / self.zoom
            right_edge = float(card_rect.right - rect.left) / self.zoom
            bottom_edge = float(card_rect.bottom - rect.top) / self.zoom
            bounds[node.id] = (x, y, right_edge, bottom_edge)
            layer = self._cards[node.id].parentElement
            last_in_layer[node.id] = layer.lastElementChild.getAttribute('data-node-id') == node.id
            layer_rect = layer.getBoundingClientRect()
            layer_bounds[node.id] = tuple(float(value) / self.zoom for value in (
                layer_rect.left - rect.left, layer_rect.top - rect.top,
                layer_rect.right - rect.left, layer_rect.bottom - rect.top))
            right = max(right, right_edge)
            bottom = max(bottom, bottom_edge)
        return bounds, layer_bounds, last_in_layer, right, bottom

    def _project_edges(self):
        """Map hidden endpoints to visible ancestors and merge displayed labels."""
        def representative(node):
            while node is not None and node.id not in self.rendered_ids:
                node = node._parent
            return node
        grouped = {}
        for source in self.nodes_flat:
            for target, label in source.to.items():
                shown_source, shown_target = representative(source), representative(target)
                if shown_source is None or shown_target is None:
                    continue
                if shown_source is shown_target and not (source is target and source is shown_source):
                    continue
                key = (shown_source, shown_target)
                if key not in grouped:
                    grouped[key] = []
                is_projected = source is not shown_source or target is not shown_target
                shown_label = ('Child: ' + label if label else 'Child') if is_projected else label
                if shown_label and shown_label not in grouped[key]:
                    grouped[key].append(shown_label)
        edges = [(source, target, ' / '.join(labels)) for (source, target), labels in grouped.items()]
        return edges

    @staticmethod
    def _label_width(label):
        """Measure label text in the browser; use an estimate without the DOM."""
        global _text_measure_context
        try:
            if _text_measure_context is None:
                from pyscript import document
                _text_measure_context = document.createElement('canvas').getContext('2d')
                _text_measure_context.font = '12px system-ui, sans-serif'
            return max(12.0, float(_text_measure_context.measureText(label).width))
        except (ImportError, AttributeError):
            # Keep routing testable in ordinary Python; wide characters need
            # roughly twice the space of Latin characters at this font size.
            return max(12.0, sum(12 if unicodedata.east_asian_width(c) in ('W', 'F') else 7 for c in label))

    def _route_edges(self, visible, bounds, layer_bounds, last_in_layer, edges):
        """Calculate path strings and label coordinates without changing the DOM."""
        flow_direction = 'TB' if self.direction in ('TB', 'BT') else 'LR'

        def plan_connections():
            """Select sides and share distinct ports among edges on each side."""
            plans, port_members = [], {}
            for i, (source, target, label) in enumerate(edges):
                sx0, sy0, sx1, sy1 = bounds[source.id]
                tx0, ty0, tx1, ty1 = bounds[target.id]
                if flow_direction == 'TB' and sy1 < ty0:
                    source_side, target_side, mode = 'bottom', 'top', 'forward'
                elif flow_direction == 'LR' and sx1 < tx0:
                    source_side, target_side, mode = 'right', 'left', 'forward'
                elif flow_direction == 'TB':
                    target_side = 'right' if last_in_layer[target.id] else 'top'
                    source_side = 'right' if last_in_layer[source.id] else 'bottom'
                    mode = 'rail'
                else:
                    source_side = 'bottom' if last_in_layer[source.id] else 'right'
                    source_side, target_side, mode = source_side, 'left', 'rail'
                plans.append((source, target, label, source_side, target_side, mode))
                for node, side, role in ((source, source_side, 'out'), (target, target_side, 'in')):
                    key = (node, side)
                    if key not in port_members:
                        port_members[key] = []
                    port_members[key].append((i, role))
            return plans, port_members

        def port(node, side, index, role):
            """Get this connection's point among the ports on the chosen side."""
            x0, y0, x1, y1 = bounds[node.id]
            members = port_members[(node, side)]
            fraction = (members.index((index, role)) + 1) / (len(members) + 1)
            if side == 'top':
                return (x0 + (x1-x0)*fraction, y0 - 2)
            if side == 'bottom':
                return (x0 + (x1-x0)*fraction, y1)
            if side == 'left':
                return (x0 - 2, y0 + (y1-y0)*fraction)
            return (x1, y0 + (y1-y0)*fraction)

        def vertical_forward(source, target, sx, sy, tx, ty):
            """Route top-to-bottom and place the label between enclosing groups."""
            mid = (sy + ty) / 2
            path_data = 'M %s %s V %s H %s V %s' % (sx, sy, mid, tx, ty)
            source_chain, target_chain = [], []
            node = source
            while node is not None:
                source_chain.append(node)
                node = node._parent
            node = target
            while node is not None:
                target_chain.append(node)
                node = node._parent
            source_branch = next((n for n in reversed(source_chain) if n not in target_chain), None)
            target_branch = next((n for n in reversed(target_chain) if n not in source_chain), None)
            gap_start = bounds[source_branch.id][3] if source_branch else sy
            gap_end = bounds[target_branch.id][1] if target_branch else ty
            label_line_y = (gap_start + gap_end) / 2 if gap_start < gap_end else mid
            label_x = (sx if label_line_y < mid else tx) + 5
            # Text stays upright when BT paths are mirrored.
            label_y = label_line_y + 5 if self.direction == 'BT' else label_line_y - 5
            return path_data, label_x, label_y

        def horizontal_forward(label, sx, sy, tx, ty):
            """Route left-to-right and center the label within the gap."""
            mid = (sx + tx) / 2
            path_data = 'M %s %s H %s V %s H %s' % (sx, sy, mid, ty, tx)
            label_x = mid - self._label_width(label) / 2
            label_y = (sy + ty) / 2 - 5
            return path_data, label_x, label_y

        def vertical_rail(source, target, source_side, target_side, sx, sy, tx, ty, i, rail_index):
            """Route a return edge along a local rail to the right."""
            edge_right = max(sx, tx)
            for obstacle, depth in visible:
                if obstacle is source or obstacle is target or (obstacle.unfolded and obstacle.children):
                    continue
                ox0, oy0, ox1, oy1 = bounds[obstacle.id]
                if oy1 >= min(sy, ty) and oy0 <= max(sy, ty):
                    edge_right = max(edge_right, ox1)
            rail = edge_right + 30 + rail_index * 20
            out_y = layer_bounds[source.id][3] + 8 + (i % 3) * 4
            in_y = layer_bounds[target.id][1] - 8 - (i % 3) * 4
            if source_side == 'right' and target_side == 'right':
                path_data = 'M %s %s H %s V %s H %s' % (sx, sy, rail, ty, tx + 2)
            elif source_side == 'right':
                path_data = 'M %s %s H %s V %s H %s V %s' % (sx, sy, rail, in_y, tx, ty)
            elif target_side == 'right':
                path_data = 'M %s %s V %s H %s V %s H %s' % (sx, sy, out_y, rail, ty, tx + 2)
            else:
                path_data = 'M %s %s V %s H %s V %s H %s V %s' % (sx, sy, out_y, rail, in_y, tx, ty)
            return path_data, rail + 4, (sy + ty) / 2 - 4

        def horizontal_rail(source, target, label, source_side, sx, sy, tx, ty, i, rail_index):
            """Route a return edge along a local rail below the nodes."""
            edge_bottom = max(sy, ty)
            for obstacle, depth in visible:
                if obstacle is source or obstacle is target or (obstacle.unfolded and obstacle.children):
                    continue
                ox0, oy0, ox1, oy1 = bounds[obstacle.id]
                if ox1 >= min(sx, tx) and ox0 <= max(sx, tx):
                    edge_bottom = max(edge_bottom, oy1)
            rail = edge_bottom + 30 + rail_index * 20
            out_x = layer_bounds[source.id][2] + 8 + (i % 3) * 4
            in_x = layer_bounds[target.id][0] - 8 - (i % 3) * 4
            if source_side == 'bottom':
                path_data = 'M %s %s V %s H %s V %s H %s' % (sx, sy, rail, in_x, ty, tx)
            else:
                path_data = 'M %s %s H %s V %s H %s V %s H %s' % (sx, sy, out_x, rail, in_x, ty, tx)
            # The rail starts at the bottom port or out_x, depending on side.
            rail_start = sx if source_side == 'bottom' else out_x
            label_x = (rail_start + in_x) / 2 - self._label_width(label) / 2
            return path_data, label_x, rail - 5

        label_boxes = []
        def label_position(x, y, label):
            """Move a label down if it collides with an earlier label."""
            w = self._label_width(label)
            candidate = y
            while any(x < px + pw and x + w > px and candidate - 12 < py and candidate + 3 > py - 12
                      for px, py, pw in label_boxes):
                candidate += 17
            label_boxes.append((x, candidate, w))
            return candidate

        plans, port_members = plan_connections()
        routes, rail_index = [], 0
        for i, (source, target, label, source_side, target_side, mode) in enumerate(plans):
            sx, sy = port(source, source_side, i, 'out')
            tx, ty = port(target, target_side, i, 'in')
            if mode == 'forward' and flow_direction == 'TB':
                path_data, label_x, label_y = vertical_forward(source, target, sx, sy, tx, ty)
            elif mode == 'forward':
                path_data, label_x, label_y = horizontal_forward(label, sx, sy, tx, ty)
            elif flow_direction == 'TB':
                path_data, label_x, label_y = vertical_rail(
                    source, target, source_side, target_side, sx, sy, tx, ty, i, rail_index)
                rail_index += 1
            else:
                path_data, label_x, label_y = horizontal_rail(
                    source, target, label, source_side, sx, sy, tx, ty, i, rail_index)
                rail_index += 1
            if label:
                label_y = label_position(label_x, label_y, label)
            routes.append((path_data, label, label_x, label_y))
        return routes

    def _paint_svg(self, width, height, routes, right, bottom, edges):
        """Apply a calculated drawing to the SVG; node HTML remains untouched."""
        from pyscript import document
        svg_ns = 'http://www.w3.org/2000/svg'
        def svg_el(name, attrs):
            el = document.createElementNS(svg_ns, name)
            for key, value in attrs.items():
                el.setAttribute(key, str(value))
            return el

        canvas, lines = self._canvas, self._lines
        canvas.style.width = str(width) + 'px'
        canvas.style.height = str(height) + 'px'
        lines.setAttribute('width', str(width))
        lines.setAttribute('height', str(height))
        self._apply_zoom()
        lines.replaceChildren()
        defs = svg_el('defs', {})
        marker = svg_el('marker', {'id': 'flow-arrow', 'viewBox': '0 0 10 10', 'refX': '9', 'refY': '5', 'markerWidth': '7', 'markerHeight': '7', 'orient': 'auto-start-reverse'})
        marker.appendChild(svg_el('path', {'d': 'M 0 0 L 10 5 L 0 10 z', 'fill': 'context-stroke'}))
        defs.appendChild(marker)
        lines.appendChild(defs)
        self._edge_elements = []
        for (path_data, label, label_x, label_y), (source, target, _) in zip(routes, edges):
            path = svg_el('path', {'d': path_data, 'class': 'flow-edge', 'marker-end': 'url(#flow-arrow)'})
            if self.direction == 'BT':
                path.setAttribute('transform', 'translate(0 %s) scale(1 -1)' % bottom)
                label_y = bottom - label_y
            elif self.direction == 'RL':
                path.setAttribute('transform', 'translate(%s 0) scale(-1 1)' % right)
                label_x = right - label_x - self._label_width(label)
            lines.appendChild(path)
            text = None
            if label:
                text = svg_el('text', {'x': label_x, 'y': label_y, 'class': 'flow-label'})
                text.textContent = label
                lines.appendChild(text)
            self._edge_elements.append((source, target, path, text))

# Optional lowercase alias matching the proposed API.
diagram = Diagram
# Python's "from" is a keyword: node.from_ is the normal spelling.
setattr(Node, 'from', property(lambda self: self.from_))
