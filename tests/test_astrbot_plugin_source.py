from __future__ import annotations

import ast
from pathlib import Path


PLUGIN_MAIN = (
    Path(__file__).resolve().parents[1] / "astrbot_plugin_nalmai" / "main.py"
)


def _tree() -> ast.Module:
    return ast.parse(PLUGIN_MAIN.read_text(encoding="utf-8"))


def _registered_filter_commands() -> dict[str, set[str]]:
    tree = _tree()
    commands: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or not decorator.args:
                continue
            function = decorator.func
            if not (
                isinstance(function, ast.Attribute)
                and function.attr == "command"
                and isinstance(function.value, ast.Name)
                and function.value.id == "filter"
                and isinstance(decorator.args[0], ast.Constant)
            ):
                continue
            command = str(decorator.args[0].value)
            aliases: set[str] = set()
            for keyword in decorator.keywords:
                if keyword.arg != "alias" or not isinstance(keyword.value, ast.Set):
                    continue
                aliases = {
                    str(element.value)
                    for element in keyword.value.elts
                    if isinstance(element, ast.Constant)
                }
            commands[command] = aliases
    return commands


def test_grouped_commands_register_explicit_case_aliases() -> None:
    commands = _registered_filter_commands()
    for command in (
        "assetsync",
        "b50",
        "bind",
        "help",
        "status",
        "unbind",
        "update",
    ):
        assert commands[f"nalmai {command}"] == {
            f"Nalmai {command}",
            f"NAlmai {command}",
            f"NALMAI {command}",
        }



def test_direct_mention_commands_are_registered() -> None:
    commands = {
        command
        for command in _registered_filter_commands()
        if " " not in command
    }

    assert commands == {
        "assetsync",
        "b50",
        "bind",
        "help",
        "status",
        "unbind",
        "update",
    }


def test_direct_commands_delegate_to_group_handlers() -> None:
    source = PLUGIN_MAIN.read_text(encoding="utf-8")
    for command in (
        "help",
        "bind",
        "update",
        "b50",
        "asset_sync",
        "status",
        "unbind",
    ):
        assert f"self.{command}_command(" in source


def test_commands_use_strict_shape_validation_without_command_group() -> None:
    source = PLUGIN_MAIN.read_text(encoding="utf-8")
    assert "filter.command_group" not in source
    for command in (
        "help",
        "bind",
        "update",
        "b50",
        "assetsync",
        "status",
        "unbind",
    ):
        assert f'_valid_command_message(event, "{command}"' in source


def test_direct_commands_stop_other_matching_handlers() -> None:
    tree = _tree()
    shortcuts = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name.endswith("_shortcut_command")
    }

    assert set(shortcuts) == {
        "asset_sync_shortcut_command",
        "b50_shortcut_command",
        "bind_shortcut_command",
        "help_shortcut_command",
        "status_shortcut_command",
        "unbind_shortcut_command",
        "update_shortcut_command",
    }
    for node in shortcuts.values():
        calls = {
            child.func.attr
            for child in ast.walk(node)
            if isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
        }
        assert "stop_event" in calls
