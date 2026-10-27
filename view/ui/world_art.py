from __future__ import annotations

import os

import pygame

from .asset_loader import AssetLoader, IMAGES_DIR, SUPPORTED_EXTENSIONS
from .placeholders import make_placeholder

TILE_SIZE = 128


class WorldArt:

    def __init__(self, world_id):
        self.world_id = str(world_id or "world")
        self._background = None
        self._icons = {}

    def _first_asset(self, names, size):
        for name in names:
            if AssetLoader.asset_exists(name):
                return AssetLoader.load_asset(name, size)
        return AssetLoader.load_asset(names[-1] if names else "unknown", size)

    def portrait(self, character_id, size=(64, 72)):
        character_id = str(character_id or "unknown")
        key = ("portrait", character_id, size)
        if key not in self._icons:
            self._icons[key] = self._first_asset(
                (
                    "characters/%s" % character_id,
                    "characters/%s_portrait" % character_id,
                    "characters/default",
                ),
                size,
            )
        return self._icons[key]

    def organization_icon(self, node, size=(48, 48)):
        node = node or {}
        node_id = str(node.get("id") or "unknown")
        polity = str(node.get("polity") or "")
        domain = str(node.get("domain") or "")
        key = ("organization", node_id, polity, domain, size)
        if key not in self._icons:
            names = ["organizations/%s" % node_id]
            if polity:
                names.append("organizations/%s" % polity)
            if domain:
                names.append("organizations/%s" % domain)
            names.append("organizations/default")
            self._icons[key] = self._first_asset(names, size)
        return self._icons[key]

    def item_icon(self, item, size=(52, 52)):
        item = item or {}
        item_id = str(item.get("id") or "unknown")
        icon = str(item.get("icon") or "items/%s" % item_id)
        key = ("item", item_id, icon, size)
        if key not in self._icons:
            self._icons[key] = AssetLoader.load_asset(icon, size)
        return self._icons[key]

    def skill_icon(self, skill_id, size=(38, 38)):
        skill_id = str(skill_id or "unknown")
        key = ("skill", skill_id, size)
        if key not in self._icons:
            self._icons[key] = AssetLoader.load_asset(
                "skills/%s" % skill_id, size
            )
        return self._icons[key]

    def background(self, size=(1280, 720)):
        if self._background is None:
            self._background = self._build_background(size)
        return self._background

    def _tile_files(self):
        tiles_root = os.path.join(IMAGES_DIR, "tilesets")
        folder = os.path.join(tiles_root, self.world_id)
        if os.path.isdir(folder):
            files = sorted(
                name
                for name in os.listdir(folder)
                if os.path.splitext(name)[1].lower() in SUPPORTED_EXTENSIONS
            )
            if files:
                return [os.path.join(folder, name) for name in files]
        if os.path.isdir(tiles_root):
            prefix = self.world_id + "_"
            files = sorted(
                name
                for name in os.listdir(tiles_root)
                if name.startswith(prefix)
                and os.path.splitext(name)[1].lower() in SUPPORTED_EXTENSIONS
            )
            if files:
                return [os.path.join(tiles_root, name) for name in files]
        return []

    @staticmethod
    def _load_tile(path):
        try:
            raw = pygame.image.load(path)
        except Exception:
            return None
        try:
            tile = raw.convert_alpha()
        except Exception:
            try:
                tile = raw.convert()
            except Exception:
                tile = raw
        return pygame.transform.smoothscale(tile, (TILE_SIZE, TILE_SIZE))

    def _build_tileset(self, size):
        files = self._tile_files()
        if not files:
            return None
        tiles = [
            tile
            for tile in (self._load_tile(path) for path in files)
            if tile is not None
        ]
        if not tiles:
            return None
        surface = pygame.Surface(size)
        surface.fill((12, 16, 24))
        columns = (size[0] + TILE_SIZE - 1) // TILE_SIZE
        rows = (size[1] + TILE_SIZE - 1) // TILE_SIZE
        for row in range(rows):
            for column in range(columns):
                tile = tiles[(row + column * 3) % len(tiles)]
                surface.blit(tile, (column * TILE_SIZE, row * TILE_SIZE))
        return surface

    def _build_background(self, size):
        for name in (
            "tilesets/%s_background" % self.world_id,
            "tilesets/%s_bg" % self.world_id,
            "tilesets/%s" % self.world_id,
        ):
            if AssetLoader.asset_exists(name):
                return AssetLoader.load_asset(name, size)
        tiled = self._build_tileset(size)
        if tiled is not None:
            return tiled
        return make_placeholder(
            "tilesets/%s" % self.world_id,
            size,
            AssetLoader.PLACEHOLDER_LABEL,
        )


__all__ = ["WorldArt"]
