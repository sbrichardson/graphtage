import csv
import json
import random
from functools import partial, wraps
from io import StringIO
from typing import FrozenSet, Tuple
from unittest import TestCase

import yaml
from tqdm import trange

import graphtage
from graphtage import xml


STR_BYTES: FrozenSet[str] = frozenset([
    chr(i) for i in range(32, 127)
] + ['\n', '\t', '\r'])
LETTERS: Tuple[str, ...] = tuple(
    chr(i) for i in range(ord('a'), ord('z'))
) + tuple(
    chr(i) for i in range(ord('A'), ord('Z'))
)

FILETYPE_TEST_PREFIX = 'test_'
FILETYPE_TEST_SUFFIX = '_formatting'


def filetype_test(test_func=None, *, test_equality=True):
    if test_func is None:
        return partial(filetype_test, test_equality=test_equality)

    @wraps(test_func)
    def wrapper(self: 'TestFormatting'):
        name = test_func.__name__
        if not name.startswith(FILETYPE_TEST_PREFIX):
            raise ValueError(f'@filetype_test {name} must start with "{FILETYPE_TEST_PREFIX}"')
        elif not name.endswith(FILETYPE_TEST_SUFFIX):
            raise ValueError(f'@filetype_test {name} must end with "{FILETYPE_TEST_SUFFIX}"')
        filetype_name = name[len(FILETYPE_TEST_PREFIX):-len(FILETYPE_TEST_SUFFIX)]
        if filetype_name not in graphtage.FILETYPES_BY_TYPENAME:
            raise ValueError(f'Filetype "{filetype_name}" for @filetype_test {name} not found in graphtage.FILETYPES_BY_TYPENAME')
        filetype = graphtage.FILETYPES_BY_TYPENAME[filetype_name]
        formatter = filetype.get_default_formatter()

        for _ in trange(1000):
            orig_obj, str_representation = test_func(self)
            with graphtage.utils.Tempfile(str_representation.encode('utf-8')) as t:
                tree = filetype.build_tree(t)
                stream = StringIO()
                printer = graphtage.printer.Printer(out_stream=stream, ansi_color=False)
                formatter.print(printer, tree)
                printer.flush(final=True)
                formatted_str = stream.getvalue()
            with graphtage.utils.Tempfile(formatted_str.encode('utf-8')) as t:
                try:
                    new_obj = filetype.build_tree(t)
                except Exception as e:
                    self.fail(f"""{filetype_name.upper()} decode error {e}: Original version:
{orig_obj!r}
Formatted version:
{formatted_str!s}""")
            if test_equality:
                self.assertEqual(tree, new_obj)

    return wrapper


class TestFormatting(TestCase):
    @staticmethod
    def make_random_int() -> int:
        return random.randint(-1000000, 1000000)

    @staticmethod
    def make_random_float() -> float:
        return random.random()

    @staticmethod
    def make_random_bool() -> bool:
        return random.choice([True, False])

    @staticmethod
    def make_random_str(exclude_bytes: FrozenSet[str] = frozenset()) -> str:
        return ''.join(random.choices(list(STR_BYTES - exclude_bytes), k=random.randint(0, 128)))

    @staticmethod
    def make_random_non_container(exclude_bytes: FrozenSet[str] = frozenset()):
        return random.choice([
            TestFormatting.make_random_int,
            TestFormatting.make_random_bool,
            TestFormatting.make_random_float,
            partial(TestFormatting.make_random_str, exclude_bytes=exclude_bytes)
        ])()

    @staticmethod
    def _make_random_obj(obj_stack):
        r = random.random()
        NON_CONTAINER_PROB = 0.1
        CONTAINER_PROB = (1.0 - NON_CONTAINER_PROB) / 2.0
        if r <= NON_CONTAINER_PROB:
            ret = TestFormatting.make_random_non_container()
        elif r <= NON_CONTAINER_PROB + CONTAINER_PROB:
            ret = []
            obj_stack.append(ret)
        else:
            ret = {}
            obj_stack.append(ret)
        return ret

    @staticmethod
    def make_random_obj(force_string_keys: bool = False, allow_empty_containers: bool = True):
        obj_stack = []
        ret = TestFormatting._make_random_obj(obj_stack)
        if allow_empty_containers:
            min_container_size = 0
        else:
            min_container_size = 1

        def container_size() -> int:
            return max(int(random.betavariate(0.75, 5) * 10), min_container_size)

        while obj_stack:
            expanding = obj_stack.pop()
            if isinstance(expanding, dict):
                for _ in range(container_size()):
                    if force_string_keys:
                        expanding[TestFormatting.make_random_str()] = TestFormatting._make_random_obj(obj_stack)
                    else:
                        expanding[TestFormatting.make_random_non_container()] = TestFormatting._make_random_obj(obj_stack)
            else:
                for _ in range(container_size()):
                    expanding.append(TestFormatting._make_random_obj(obj_stack))
        return ret

    def test_formatter_coverage(self):
        for name in graphtage.FILETYPES_BY_TYPENAME.keys():
            if not hasattr(self, f'test_{name}_formatting'):
                self.fail(f"Filetype {name} is missing a `test_{name}_formatting` test function")

    @filetype_test
    def test_json_formatting(self):
        orig_obj = TestFormatting.make_random_obj(force_string_keys=True)
        return orig_obj, json.dumps(orig_obj)

    @filetype_test
    def test_csv_formatting(self):
        orig_obj = [
            [TestFormatting.make_random_non_container(
                exclude_bytes=frozenset('\n\r\t,"\'')
            ) for _ in range(random.randint(0, 10))]
            for _ in range(random.randint(0, 10))
        ]
        s = StringIO()
        writer = csv.writer(s)
        for row in orig_obj:
            writer.writerow(row)
        return orig_obj, s.getvalue()

    @staticmethod
    def make_random_xml() -> xml.XMLElementObj:
        ret = xml.XMLElementObj('', {})
        elem_stack = [ret]
        while elem_stack:
            elem = elem_stack.pop()
            elem.tag = ''.join(random.choices(LETTERS, k=random.randint(1, 20)))
            elem.attrib = {
               ''.join(random.choices(LETTERS, k=random.randint(1, 10))): TestFormatting.make_random_str()
               for _ in range(int(random.betavariate(0.75, 5) * 10))
            }
            if random.random() <= 0.5:
               elem.text = TestFormatting.make_random_str()
            elem.children = [xml.XMLElementObj('', {}) for _ in range(int(random.betavariate(0.75, 5) * 10))]
            elem_stack.extend(elem.children)
        return ret

    # Do not test equality for XML because the XMLFormatter auto-indents and thereby adds extra spaces to element text
    @filetype_test(test_equality=False)
    def test_xml_formatting(self):
        orig_obj = self.make_random_xml()
        return orig_obj, str(orig_obj)

    def test_html_formatting(self):
        # For now, HTML support is implemented through XML, so we don't need a separate test.
        # However, test_formatter_coverage will complain unless this function is here!
        pass

    @filetype_test
    def test_yaml_formatting(self):
        orig_obj = TestFormatting.make_random_obj(allow_empty_containers=False)
        s = StringIO()
        yaml.dump(orig_obj, s, Dumper=graphtage.yaml.Dumper)
        return orig_obj, s.getvalue()
