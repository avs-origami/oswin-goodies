import datetime
import pathlib
from typing import Any

import attrs
import ipdb
import jax.tree_util as jtu
import numpy as np
import orbax
import orbax.checkpoint as ocp
from attrs import asdict
from flax.training import orbax_utils

from og.cfg_utils import Cfg


class EzManager:
    def __init__(self, mngr: ocp.CheckpointManager):
        self.mngr = mngr

    def wait_until_finished(self):
        return self.mngr.wait_until_finished()

    def save_ez(self, step: int, items: Any):
        if isinstance(items, dict):
            return self._save_ez_dict(step, items)

        return self._save_ez(step, items)

    def _save_ez_dict(self, step: int, items: dict):
        args = {}

        for k, v in items.items():
            if isinstance(v, Cfg):
                # Call asdict on all instances of Cfg. Save using JSON.
                arg = ocp.args.JsonSave(v.asdict())
            elif attrs.has(v):
                # Call asdict on all instances of attrs. Save using JSON.
                arg = ocp.args.JsonSave(asdict(v))
            else:
                # Save as PyTree.
                arg = ocp.args.StandardSave(v)

            args[k] = arg

        self.mngr.save(step, args=ocp.args.Composite(**args))
        ckpt_path = self.mngr._get_save_directory(step, self.mngr.directory)
        return ckpt_path

    def _save_ez(self, step: int, items: Any):
        self.mngr.save(step, args=ocp.args.StandardSave(items))
        ckpt_path = self.mngr._get_save_directory(step, self.mngr.directory)
        return ckpt_path


def get_ckpt_manager(ckpt_dir: pathlib.Path, item_names: list[str] | None, max_to_keep: int = 100):
    options = ocp.CheckpointManagerOptions(max_to_keep=max_to_keep, step_format_fixed_length=5)
    mngr = ocp.CheckpointManager(ckpt_dir, item_names=item_names, options=options)
    return EzManager(mngr)


def load_cfg_from_ckpt(ckpt_path: pathlib.Path, name: str) -> Cfg:
    handler = ocp.CompositeCheckpointHandler(name)
    ckpter = ocp.Checkpointer(handler)

    restore_dict = {name: ocp.args.JsonRestore()}
    ckpt_dict = ckpter.restore(ckpt_path, ocp.args.Composite(**restore_dict))
    cfg = Cfg.fromdict(ckpt_dict[name])
    return cfg


def load_from_ckpt(ckpt_path: pathlib.Path, item, name: str | None = None):
    if name is None:
        # If the item is saved directly.
        ckpter = ocp.StandardCheckpointer()
        return ckpter.restore(ckpt_path, ocp.args.StandardRestore(item))

    # Otherwise, assume that it is savaed as composite.
    handler = ocp.CompositeCheckpointHandler(name)
    ckpter = ocp.Checkpointer(handler)

    restore_dict_flat = {name: ocp.args.StandardRestore()}
    ckpt_dict_flat = ckpter.restore(ckpt_path, ocp.args.Composite(**restore_dict_flat))

    restore_dict = {name: ocp.args.StandardRestore(item)}
    ckpt_dict = ckpter.restore(ckpt_path, ocp.args.Composite(**restore_dict))

    keyleaves1, _ = jtu.tree_flatten_with_path(ckpt_dict_flat[name])
    keyleaves2, _ = jtu.tree_flatten_with_path(ckpt_dict[name])
    # jtu.tree_map(check_same_shape, keyleaves1, keyleaves2)

    keyleaves1 = {tuple(get_key_name(k) for k in kk): v for kk, v in keyleaves1}
    keyleaves2 = {tuple(get_key_name(k) for k in kk): v for kk, v in keyleaves2}

    for key1, v1 in keyleaves1.items():
        v2 = keyleaves2[key1]
        k_name = "/".join([str(s) for s in key1])
        if np.asarray(v1).shape != np.asarray(v2).shape:
            raise ValueError(f"Shape mismatch for {k_name}: {v1.shape} != {v2.shape}")

    return ckpt_dict[name]


def get_key_name(key) -> int | str:
    """Returns the name of a JAX Key."""
    if isinstance(key, jtu.SequenceKey):
        return key.idx
    elif isinstance(key, jtu.DictKey):
        return str(key.key)
    elif isinstance(key, jtu.GetAttrKey):
        return key.name
    elif isinstance(key, jtu.FlattenedIndexKey):
        return key.key
    else:
        raise ValueError(f'Unsupported KeyEntry: {type(key)}: "{key}"')
