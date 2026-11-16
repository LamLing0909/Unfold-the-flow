"""Whole-document Pydantic validation and runtime graph connections."""
import json
import sys
import unittest
from pathlib import Path

from pydantic import BaseModel, ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from diagram import Diagram, Node


class NodeModelTest(unittest.TestCase):
    def test_models_validate_original_json_and_keep_node_identity(self):
        node = Node.model_validate_json('{"id":"a","children":[{"id":"b"}],"to":{"b":"next"}}')
        self.assertIsInstance(node, BaseModel)
        self.assertEqual(node.children[0].id, 'b')
        self.assertEqual(node.edge_ids, {'b': 'next'})
        self.assertEqual(node.to, {})  # ID references are linked by Diagram.
        other = Node(id='a')
        outgoing = {node: 'edge'}
        before = hash(node)
        node.content, node.unfolded = 'changed', True
        self.assertEqual(hash(node), before)
        self.assertEqual(outgoing[node], 'edge')
        self.assertNotEqual(node, other)

    def test_entire_json_and_cycle(self):
        source = {'nodes': [
            {'id': 'a', 'to': {'b': 'forward', 'c': 'branch'}},
            {'id': 'b', 'to': {'a': 'back'}}, {'id': 'c'},
        ]}
        d = Diagram.model_validate_json(json.dumps(source))
        self.assertIsInstance(d, BaseModel)
        a, b, c = (d.get(name) for name in ('a', 'b', 'c'))
        self.assertEqual(list(a.to.items()), [(b, 'forward'), (c, 'branch')])
        self.assertEqual(b.to[a], 'back')
        self.assertEqual(a.from_, [b])
        self.assertEqual(getattr(a, 'from'), [b])
        self.assertIs(a.diagram, d)
        # The JSON representation uses IDs, not recursive Node references.
        encoded = json.loads(d.model_dump_json(by_alias=True))
        self.assertEqual(encoded['nodes'][0]['to'], source['nodes'][0]['to'])

    def test_nested_json_and_python_input(self):
        item = {'id': 'leaf'}
        for i in range(60):
            item = {'id': f'n{i}', 'unfolded': True, 'children': [item]}
        data = {'nodes': [item]}
        a = Diagram.model_validate_json(json.dumps(data))
        b = Diagram.model_validate(data)
        self.assertEqual(len(a.visible_nodes()), 61)
        self.assertEqual(len(a.get('leaf').parents), 60)
        self.assertNotEqual(a.get('leaf'), b.get('leaf'))

    def test_entire_json_reports_precise_validation_location(self):
        invalid = {'nodes': [{'id': 'outer', 'children': [{'id': 'inner', 'unfolded': 1}]}]}
        with self.assertRaises(ValidationError) as caught:
            Diagram.model_validate_json(json.dumps(invalid))
        self.assertEqual(caught.exception.errors()[0]['loc'], ('nodes', 0, 'children', 0, 'unfolded'))

    def test_strict_input_and_graph_validation(self):
        invalid = [
            {'nodes': [{'id': ''}]}, {'nodes': [{'id': '   '}]},
            {'nodes': [{'id': 4}]}, {'nodes': [{'id': 'a', 'content': 3}]},
            {'nodes': [{'id': 'a', 'unfolded': 1}]}, {'nodes': [{'id': 'a', 'children': [5]}]},
            {'nodes': [{'id': 'a', 'to': []}]}, {'nodes': [{'id': 'a', 'to': {'a': 1}}]},
            {'nodes': [{'id': 'a'}, {'id': 'a'}]}, {'nodes': [{'id': 'a', 'to': {'missing': 'x'}}]},
        ]
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(ValidationError):
                Diagram.model_validate_json(json.dumps(data))
        with self.assertRaises(ValidationError):
            Diagram.model_validate_json('{')
        with self.assertRaises(ValidationError):
            Diagram.model_validate({'nodes': [{'id': 'a', 'children': ()}]})

    def test_runtime_fields_are_public_and_instance_state_is_independent(self):
        a = Diagram.model_validate_json('{"nodes":[{"id":"a"}]}')
        b = Diagram.model_validate_json('{"nodes":[{"id":"b"}]}')
        node = a.get('a')
        node.to = {b.get('b'): 'custom'}
        node.diagram = b
        a.nodes_flat = []
        a.assets = {'icon': 'custom'}
        a.zoom = 2.0
        self.assertEqual(node.to[b.get('b')], 'custom')
        self.assertIs(node.diagram, b)
        self.assertEqual(a.nodes_flat, [])
        self.assertEqual(a.assets['icon'], 'custom')
        self.assertEqual(a.zoom, 2.0)
        for name in ('_by_id', '_layers', '_cards', '_edge_elements', '_touch_proxies'):
            self.assertIsNot(getattr(a, name), getattr(b, name))

    def test_assets_passed_by_validation_context(self):
        assets = {'preview': 'https://example.com/pic.png'}
        d = Diagram.model_validate_json('{"nodes":[]}', context={'assets': assets})
        self.assertIs(d.assets, assets)


if __name__ == '__main__':
    unittest.main()
