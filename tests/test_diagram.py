"""Pure-Python checks for graph projection and routing (no browser required)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from diagram import Diagram


class DiagramStepsTest(unittest.TestCase):
    def test_hidden_edges_project_and_restore(self):
        diagram = Diagram.model_validate({'nodes': [
            {'id': 'parent', 'children': [
                {'id': 'a', 'to': {'end': 'Done', 'b': 'Internal'}},
                {'id': 'b'},
            ]},
            {'id': 'end'},
        ]})
        def edges():
            diagram.rendered_ids = {node.id for node, _ in diagram.visible_nodes()}
            return [(a.id, b.id, label) for a, b, label in diagram._project_edges()]
        self.assertEqual(edges(), [('parent', 'end', 'Child: Done')])
        diagram.get('parent').unfolded = True
        self.assertEqual(edges(), [('a', 'end', 'Done'), ('a', 'b', 'Internal')])

    def test_routes_forward_without_dom(self):
        for direction, b_box in [('TB', (0, 100, 100, 150)), ('LR', (200, 0, 300, 50))]:
            with self.subTest(direction=direction):
                diagram = Diagram.model_validate({'direction': direction, 'nodes': [
                    {'id': 'a', 'to': {'b': 'go'}}, {'id': 'b'},
                ]})
                a, b = diagram.get('a'), diagram.get('b')
                bounds = {'a': (0, 0, 100, 50), 'b': b_box}
                routes = diagram._route_edges([(a, 0), (b, 0)], bounds, bounds,
                                               {'a': True, 'b': True}, [(a, b, 'go')])
                self.assertEqual(len(routes), 1)
                path, label, x, y = routes[0]
                self.assertEqual(label, 'go')
                self.assertTrue(path.startswith('M 50.0 50 V') if direction == 'TB'
                                else path.startswith('M 100 25.0 H'))
                self.assertIsInstance(x, (int, float))
                self.assertIsInstance(y, (int, float))

    def test_horizontal_forward_label_centered_in_gap(self):
        for direction in ('LR', 'RL'):
            with self.subTest(direction=direction):
                label = 'Child: Approved'
                diagram = Diagram.model_validate({'direction': direction, 'nodes': [
                    {'id': 'a', 'to': {'b': label}}, {'id': 'b'},
                ]})
                a, b = diagram.get('a'), diagram.get('b')
                # _route_edges uses logical left-to-right coordinates in both directions.
                bounds = {'a': (0, 0, 100, 50), 'b': (360, 0, 460, 50)}
                _, _, x, _ = diagram._route_edges(
                    [(a, 0), (b, 0)], bounds, bounds,
                    {'a': True, 'b': True}, [(a, b, label)])[0]
                self.assertAlmostEqual(x + diagram._label_width(label) / 2, 229)
                self.assertGreater(x, 100)
                self.assertLess(x + diagram._label_width(label), 358)

    def test_bt_nested_forward_label_uses_outer_group_gap(self):
        diagram = Diagram.model_validate({'direction': 'BT', 'nodes': [
            {'id': 'outer-a', 'children': [{'id': 'a', 'to': {'b': 'Done'}}]},
            {'id': 'outer-b', 'children': [{'id': 'b'}]},
        ]})
        a, b = diagram.get('a'), diagram.get('b')
        bounds = {'outer-a': (0, 0, 240, 180), 'a': (10, 20, 110, 70),
                  'outer-b': (0, 240, 240, 420), 'b': (10, 260, 110, 310)}
        _, _, _, y = diagram._route_edges(
            [(a, 1), (b, 1)], bounds, bounds, {'a': True, 'b': True}, [(a, b, 'Done')])[0]
        # In logical coordinates text is five pixels below the line; mirroring
        # places it above the line, in the gap between expanded groups.
        self.assertEqual(y, 215)

    def test_horizontal_return_label_is_on_its_rail(self):
        for direction in ('LR', 'RL'):
            with self.subTest(direction=direction):
                diagram = Diagram.model_validate({'direction': direction, 'nodes': [
                    {'id': 'a', 'to': {'b': 'Changes needed'}}, {'id': 'b'},
                ]})
                a, b = diagram.get('a'), diagram.get('b')
                bounds = {'a': (400, 0, 500, 60), 'b': (100, 0, 200, 60)}
                layers = {'a': (300, 0, 800, 60), 'b': (100, 0, 200, 60)}
                path, label, x, y = diagram._route_edges(
                    [(a, 0), (b, 0)], bounds, layers,
                    {'a': True, 'b': True}, [(a, b, 'Changes needed')])[0]
                # The horizontal rail starts at the source's bottom port,
                # not at the (much further away) edge of its layer.
                self.assertAlmostEqual(x + diagram._label_width(label) / 2, (450 + 92) / 2)
                self.assertEqual(y, 85)
                self.assertIn('V 90 H 92', path)

    def test_self_loop_has_a_route(self):
        diagram = Diagram.model_validate({'nodes': [{'id': 'a', 'to': {'a': 'again'}}]})
        a = diagram.get('a')
        bounds = {'a': (0, 0, 100, 50)}
        routes = diagram._route_edges([(a, 0)], bounds, bounds, {'a': True}, [(a, a, 'again')])
        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0][1], 'again')
        self.assertIn(' H ', routes[0][0])
        self.assertIn(' V ', routes[0][0])

class DirectionTest(unittest.TestCase):
    def test_four_directions_and_top_down_alias(self):
        for given, expected in [('TB', 'TB'), ('TD', 'TB'), ('BT', 'BT'),
                                ('LR', 'LR'), ('RL', 'RL')]:
            with self.subTest(direction=given):
                self.assertEqual(Diagram.model_validate({'direction': given, 'nodes': []}).direction, expected)

    def test_invalid_direction(self):
        with self.assertRaises(ValueError):
            Diagram.model_validate({'direction': 'sideways', 'nodes': []})

class ZoomTest(unittest.TestCase):
    def test_zoom_bounds_and_callback_without_browser(self):
        diagram = Diagram.model_validate({'nodes': []})
        seen = []
        diagram.on_zoom = seen.append
        self.assertEqual(diagram.set_zoom(0.01), 0.25)
        self.assertEqual(diagram.set_zoom(99), 4.0)
        self.assertEqual(diagram.set_zoom(1), 1.0)
        self.assertEqual(seen, [0.25, 4.0, 1.0])
        with self.assertRaises(ValueError):
            diagram.set_zoom(float('nan'))
        self.assertEqual(diagram.zoom, 1.0)

if __name__ == '__main__':
    unittest.main()
