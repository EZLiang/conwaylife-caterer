# ----------------------------------------------------------------------------------- #

from itertools import islice

def nth(iterable, n, default=None):
    temp = iterable
    return next(islice(temp, n, None), default)

# ----------------------------------------------------------------------------------- #

import inspect
from functools import wraps
from itertools import zip_longest as zipln

def typecasted(func):
    """Decorator that casts a func's arg to its type hint if possible"""
    #TODO: Allow (callable, callable, ..., callable) sequences to apply
    # each callable in order on the last's return value
    params = inspect.signature(func).parameters.items()
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Prepare list/dict of all positional/keyword args of annotation or None
        pannot, kwannot = (
          [func.__annotations__.get(p.name) for _, p in params if p.kind < 3],
          {None if p.kind - 3 else p.name: func.__annotations__.get(p.name) for _, p in params if p.kind >= 3}
          )
        # Assign default to handle **kwargs annotation if not given/callable
        if not callable(kwannot.get(None)):
            kwannot[None] = lambda x: x
        ret = func(
            *(val if hint is None else hint(val) if callable(hint) else type(hint)(val) for hint, val in zipln(pannot, args, fillvalue=pannot[-1])),
            **{a: kwannot[a](b) if a in kwannot and callable(kwannot[a]) else kwannot[None](b) for a, b in kwargs.items()}
            )
        conv = func.__annotations__.get('return')
        return conv(ret) if callable(conv) else ret
    return wrapper

# ----------------------------------------------------------------------------------- #

import asyncio
import concurrent.futures

async def await_event_or_coro(bot, event, coro, *, ret_check=None, event_check=None, timeout=None):
    """
    discord.Client.wait_for, but force-cancels on completion of
    :param:coro rather than on a timeout
    """
    future = bot.loop.create_future()
    event_check = event_check or (lambda *_, **__: True)
    try:
        listeners = bot._listeners[event.lower()]
    except KeyError:
        listeners = []
        bot._listeners[event.lower()] = listeners
    listeners.append((future, event_check))
    [done], pending = await asyncio.wait([future, coro], timeout=timeout, return_when=concurrent.futures.FIRST_COMPLETED)
    for task in pending:
        task.cancel() # does this even do anything???
    try:
        which = 'event' if event_check(*done.result()) else 'coro'
    except TypeError:
        which = 'coro'
    return {which: done.result()}
    

async def wait_for_any(ctx, events, checks, *, timeout=15.0):
    """
    ctx: Context instance
    events: Sequence of events as outlined in dpy's event reference
    checks: Sequence of check functions as outlined in dpy's docs
    timeout: asyncio.wait timeout
    
    Params events and checks must be of equal length.
    """
    mapped = list(zip(events, checks))
    futures = [ctx.bot.wait_for(event, timeout=timeout, check=check) for event, check in mapped]
    [done], pending = await asyncio.wait(futures, loop=ctx.bot.loop, timeout=timeout, return_when=concurrent.futures.FIRST_COMPLETED)
    result = done.result()
    for event, check in mapped:
        try:
            # maybe just check(result) and force multi-param checks to unpack?
            valid = check(*result) if isinstance(result, tuple) else check(result)
        except (TypeError, AttributeError, ValueError): # maybe just except Exception
            continue
        if valid:
            return {event: result}
    return None

# ----------------------------------------------------------------------------------- #
import re


@typecasted
def parse_args(args: list, regex: [re.compile], defaults: list, *, flag_parser = None) -> ([str], [str]):
    """
    Sorts `args` according to order in `regex`.
    
    If no matches for a given regex are found in `args`, the item
    in `defaults` with the same index is dropped in to replace it.
    
    If flag_parser is None:
        Extraneous arguments in `args` are left untouched, and the
        third item in this func's return tuple will consist of these
        extraneous args, if there are any. The second item will always
        be None.
    If flag_parser is not None:
        Flags will be parsed first in order for multi-word flag values
        containing whitespace not to be misconstrued as arguments.
        flag_parser() is expected to pop elements from the list it is passed.
        flag_parser()'s return value will be provided as the second item in
        this func's return tuple, and any extraneous arguments in `args`
        will be returned as the third tuple item.
    """
    assert len(regex) == len(defaults)
    # mutates args
    flags = None if flag_parser is None else flag_parser(args)
    new, regex = [], [i if isinstance(i, (list, tuple)) else [i] for i in regex]
    for ridx, rgx in enumerate(regex): 
        for aidx, arg in enumerate(args):
            if any(k.match(arg) for k in rgx if k is not None):
                new.append(arg)
                args.pop(aidx)
                break
        else: 
             new.append(defaults[ridx])
    if flag_parser is None:
        return new, None, args
    return new, flags, args

def parse_flags(flags, *, prefix='-', delim=':', quote="'", mutate=True):
    if isinstance(flags, str):
        flags = flags.split()
        mutate = False
    op = f'{delim}{quote}'
    d = {}
    in_value = False
    flag = None
    running_value = []
    to_pop = set()
    for i, term in enumerate(flags):
        if not in_value and term.startswith(prefix):
            if op in term:
                flag, term = term[len(prefix):].split(op, 1)
                in_value = True
            elif delim in term:
                flag, term = term[len(prefix):].split(delim, 1)
                d[flag] = term if term else False
            else:
                d[term[len(prefix):]] = True
            to_pop.add(i)
        if in_value:
            if term.endswith(quote):
                running_value.append(term[:-len(quote)])
                d[flag] = ' '.join(running_value)
                flag = None
                in_value = False
                running_value.clear()
            else:
                running_value.append(term)
            to_pop.add(i)
    if mutate:
        flags[:] = (v for i, v in enumerate(flags) if i not in to_pop)
        return d
    return d, [v for i, v in enumerate(flags) if i not in to_pop]

# ----------------------------------------------------------------------------------- #

import dis
import types

def attrify(func):
    """Assign nested callables to attributes of their enclosing function"""
    for nest in (types.FunctionType(i.argval, globals()) for i in dis.get_instructions(func) if isinstance(i.argval, types.CodeType)):
        setattr(func, nest.__name__, nest)
    return func

# ----------------------------------------------------------------------------------- #

def chain(nested):
    """itertools.chain() but leave strings untouched"""
    for i in nested:
        if isinstance(i, (list, tuple)):
            yield from chain(i)
        else:
            yield i

# ------------- Custom command/group decos with info pointing to cmd.py ------------- #

import dis
import inspect
import re
import types
from functools import wraps
from itertools import chain, repeat

import discord
from discord.ext import commands

from .import cmd


class HelpAttrMixin:
    @property
    def helpsafe_name(self):
        return self.qualified_name.replace(' ', '/')
    
    @property
    def invocation_args(self):
        return cmd.args.get(self.qualified_name, '')
    
    @property
    def aliases(self):
        return cmd.aliases.get(self.qualified_name, [])
    
    @aliases.setter
    def aliases(*_):
        """Eliminate "can't set attribute" when dpy tries assigning aliases"""


class Command(HelpAttrMixin, commands.Command):
    def __init__(self, callback, **kwargs):
        """
        Callback will be hidden behind the silhouette func below
        """
        self.parent = None
        self.inner = getattr(callback, 'wrapped_', callback)
        
        cbc = self.inner.__code__
        self.loc = types.SimpleNamespace(
          file = cbc.co_filename,
          start = cbc.co_firstlineno - 1,
          end = max(i for _, i in dis.findlinestarts(cbc))
          )
        self.loc.len = self.loc.end - self.loc.start
        super().__init__(callback, **kwargs)


class Group(HelpAttrMixin, commands.Group):
    def __init__(self, callback, **attrs):
        self.parent = None
        self.inner = getattr(callback, 'wrapped_', callback)
        
        cbc = self.inner.__code__
        self.loc = types.SimpleNamespace(
          file = cbc.co_filename,
          start = cbc.co_firstlineno - 1,
          end = max(i for _, i in dis.findlinestarts(cbc))
          )
        self.loc.len = self.loc.end - self.loc.start
        super().__init__(callback, **attrs)

    def command(self, *args, **kwargs):
        def decorator(func):
            kwargs.setdefault('parent', self)
            result = command(*args, **kwargs)(func)
            self.add_command(result)
            return result
        return decorator

    def group(self, *args, **kwargs):
        def decorator(func):
            kwargs.setdefault('parent', self)
            result = group(*args, **kwargs)(func)
            self.add_command(result)
            return result
        return decorator


def give_args(callback):
    argspec = inspect.getfullargspec(callback)
    arguments = argspec.kwonlyargs
    defaults = argspec.kwonlydefaults
    annotations = argspec.annotations
    # separate regexes from converters because they're both in annotations
    regexes = {}
    converters = {}
    for key, val in annotations.items():
        # assume val is a tuple at first
        if callable(val[-1]): # returns false for strings (and ofc for tuples w/ non-callable last element)
            regexes[key] = [re.compile(i) for i in val[:-1]]
            converters[key] = val[-1]
            continue
        regexes[key] = re.compile(val) if isinstance(val, str) else [re.compile(i) for i in val]
        converters[key] = None
    if defaults is None:
        defaults = {}
    
    async def silhouette(self, ctx=None, *dpyargs, __invoking=False, **kwargs):
        # XXX TODO: fix hacky (figure out how to get ctx to always pass self.cog when invoking)
        if ctx is None or not isinstance(self, commands.Cog):
            self, ctx = self.cog, self
        if __invoking: # bypass converters
            return await callback(self, ctx, *dpyargs, **kwargs)
        [*args_], flags, _ = parse_args(
            dpyargs,
            map(regexes.get, arguments),
            map(defaults.get, arguments),
            flag_parser=parse_flags if 'flags' in arguments else None
            )
        params = {
            **kwargs,
            **{
                k: converters[k](v) if callable(converters[k]) and v is not None else v
                for k, v in zip(arguments, args_)
                if k != 'flags'
              }
            }
        if 'flags' in arguments:
            params['flags'] = flags
        return await callback(self, ctx, **params)
    
    silhouette.wrapped_ = callback
    silhouette.__doc__ = callback.__doc__
    return silhouette


def command(brief=None, name=None, cls=Command, args=False, **attrs):
    return lambda func: commands.command(name or func.__name__, cls, brief=brief, **attrs)(
      give_args(func) if args else func
    )
    

def group(brief=None, name=None, *, invoke_without_command=True, **kwargs):
    return command(brief, name, cls=Group, invoke_without_command=invoke_without_command, **kwargs)

# ----------------------------- For uploading assets -------------------------------- #

import json

def extract_rule_info(fp, colors_as_json=True):
    """
    Extract rulename and colors from a ruletable file.
    """
    if isinstance(fp, bytes):
        fp = fp.splitlines()
    elif isinstance(fp, discord.File):
        fp.reset()
        fp = fp.fp
    else:
        fp.seek(0)
    in_colors = False
    name, n_states, colors  = None, 0, {}
    lines = (
      (i.decode().strip().split('#', 1)[0] for i in fp)
      if colors_as_json else
      (i.strip().split('#', 1)[0] for i in fp)
    )
    for line in lines:
        if not line:
            continue
        if line.startswith(('n_states:', 'num_states=')):
            n_states = int(line.split('=')[-1].split(':')[-1].strip())
            continue
        if line.startswith('@RULE'):
            name = line.partition(' ')[-1]
            continue
        if name == '':
            # Captures rulename if on own line after @RULE
            name = line
            continue
        if line.startswith('@'):
            # makeshift state flag (indicates whether inside @COLORS declaration)
            in_colors = line.startswith('@COLORS')
            continue
        if in_colors:
            # '0    255 255 255   random comments' ->
            # {0: (255, 255, 255)}
            state, rgb = line.split(None, 1)
            colors[state] = tuple(map(int, rgb.split()[:3]))
    return name, n_states, (json.dumps(colors or {}) if colors_as_json else colors)

# --------------------------- For rule-color shenanigans ---------------------------- #

from math import ceil

NUMS = {
  **{num: chr(64+num) for num in range(25)},
  **{num: chr(110+ceil(num/24)) + chr(64+(num%24 or 24)) for num in range(25, 256)},
    0: '.'
  }
STATES = {v: k for k, v in NUMS.items()}
'''
STATES = {
  **{val:
    ord(val) - 64
    if len(val) == 1
    else 24*ord(val[0]) + ord(val[1]) - 2728
    for val in NUMS.values()}
  }
'''

def state_from(val: (int, str)):
    return NUMS[val] if isinstance(val, int) else STATES[val]

class ColorRange:
    def __init__(self, n_states, start=(255,0,0), end=(255,255,0), *, first=0):
        self.n_states = n_states
        self.first = first
        self.start = start
        self.end = end
        self.avgs = [(final-initial)/n_states for initial, final in zip(start, end)]
    
    def __iter__(self):
        for state in range(self.n_states):
            yield tuple(int(initial+level*state) for initial, level in zip(self.start, self.avgs))
    
    def __reversed__(self):
        return self.__class__(self.n_states, self.end, self.start)
    
    def __str__(self):
        return '\n'.join(f"{i} {' '.join(map(str,v))}" for i, v in enumerate(self, self.first))
    
    def at(self, state):
        if not self.first <= state <= self.first+self.n_states:
            raise ValueError('Requested state out of range')
        return tuple(int(initial+level*state) for initial, level in zip(self.start, self.avgs))
    
    def to_dict(self):
        return dict(zip((state_from(self.first+i) for i in range(self.n_states)), self))

def colorpatch(states: dict, n_states: int, fg=None, bg=None, start=(255,255,0), end=(255,0,0)):
    bg, fg = bg or (54, 57, 62), fg or (255, 255, 255)
    if n_states < 3:
        return states.get('0', bg), {
          'o': states.get('1', fg),
          'b': states.get('0', bg)  # I don't even know man
          }
    crange = ColorRange(n_states, start, end)
    return states.get('0', bg), {'.' if i == 0 else state_from(i): states.get(str(i), crange.at(i) if i else bg) for i in range(n_states)}

# -------------------------------------- Misc --------------------------------------- #
from itertools import cycle

def scale(li, mul, chunk=1, grid=None, grdiv=1):
    """
    scale([a, b, c], 2) => (a, a, b, b, c, c)
    scale([a, b, c], 2, 3) => (a, b, c, a, b, c)
    """
    zipped = zip(*[iter(li)] * chunk)
    if grid is None or mul == 1:
        return [j for i in zipped for _ in range(mul) for j in i]
    if grdiv == 1:
        return [j if edge else [grid] * len(j) for i in zipped for edge in range(mul) for j in i]
    offsets = cycle(range(mul * grdiv))
    return [j if cont else [grid] * len(j) for i in zipped for edge, cont in zip(range(mul), offsets) for j in i]

def fix(seq, chunk):
    # ***UNUSED***
    # just assume li is a 2d array because that's my only use case
    return [tuple(zip(*[iter(row)] * chunk)) for row in seq]


async def get_page(ctx, msg, emoji='⬅➡', timeout=15.0):
    left, right = emoji
    for r in emoji:
        await msg.add_reaction(r)
    try:
        rxn, _ = await ctx.bot.wait_for('reaction_add', timeout=timeout, check=lambda rxn, usr: usr.id == ctx.author.id and rxn.emoji in emoji and rxn.message.id == msg.id)
    except asyncio.TimeoutError:
        for rxn_ in msg.reactions:
            await msg.remove_reaction(rxn_, ctx.guild.me)
    else:
        try:
            await msg.remove_reaction(rxn, msg.author)
        except Exception:
            pass
        return rxn.emoji == left, rxn.emoji == right


def parse_nutshell_range(s):
    r, step = s, '1'
    if '+' in s:
        r, step = r.split('+', 1)
    begin, end = r.split('..', 1)
    return range(int(begin.strip()), 1 + int(end.strip()), int(step.strip()))


def flatten_range_list(li):
    return {t for s in li for t in ([int(s)] if s.isnumeric() else parse_nutshell_range(s))}


def get_rule_from_wiki(rulename, session):
    async with session.get(
            f'https://conwaylife.com/w/api.php?action=parse&format=json&prop=wikitext&page=RULE:{rulename}'
    ) as resp:
        b = await resp.json()
    try:
        rulefile = b["parse"]["wikitext"]["*"]
    except KeyError:  # rule not found
        raise FileNotFoundError("The specified rulefile was not found")
    return rulefile
