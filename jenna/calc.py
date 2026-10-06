"""Scientific calculator for Jenna - the model is bad at arithmetic, so every number she computes comes from here.

Safe: the expression is parsed into a syntax tree and only numbers, + - * / // % ** (or ^), parentheses and
the functions/constants below are allowed. No eval(), no names, no attribute access.

Examples: "15% of 80", "2^10", "sqrt(144)", "sin(30)" (degrees by default), "log(1000)", "ln(e)",
"5!", "comb(10, 3)", "mean(4, 8, 15)", "(29*12) - 290", "round(2500/3, 2)".
"""
import ast
import math
import operator
import re
import statistics

MAX_EXP = 1000          # 10**1000 is fine, 10**10**10 would hang
MAX_FACT = 170          # 171! overflows a float anyway

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: None}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
CONSTANTS = {"pi": math.pi, "e": math.e, "tau": math.tau, "inf": math.inf}


def _factorial(n):
    if n != int(n) or n < 0:
        raise ValueError("factorial needs a whole number >= 0")
    if n > MAX_FACT:
        raise ValueError(f"factorial is capped at {MAX_FACT}!")
    return math.factorial(int(n))


def _functions(deg):
    to_rad = math.radians if deg else (lambda x: x)
    from_rad = math.degrees if deg else (lambda x: x)
    return {
        "sqrt": math.sqrt, "cbrt": lambda x: math.copysign(abs(x) ** (1 / 3), x), "abs": abs,
        "sin": lambda x: math.sin(to_rad(x)), "cos": lambda x: math.cos(to_rad(x)), "tan": lambda x: math.tan(to_rad(x)),
        "asin": lambda x: from_rad(math.asin(x)), "acos": lambda x: from_rad(math.acos(x)),
        "atan": lambda x: from_rad(math.atan(x)), "atan2": lambda y, x: from_rad(math.atan2(y, x)),
        "sinh": math.sinh, "cosh": math.cosh, "tanh": math.tanh,
        "log": lambda x, base=10: math.log(x, base), "log10": math.log10, "log2": math.log2, "ln": math.log,
        "exp": math.exp, "pow": lambda x, y: _pow(x, y), "hypot": math.hypot,
        "floor": math.floor, "ceil": math.ceil, "round": lambda x, n=0: round(x, int(n)) if n else round(x),
        "factorial": _factorial, "comb": lambda n, k: math.comb(int(n), int(k)), "perm": lambda n, k: math.perm(int(n), int(k)),
        "gcd": lambda *a: math.gcd(*map(int, a)), "lcm": lambda *a: math.lcm(*map(int, a)),
        "min": min, "max": max, "sum": lambda *a: sum(a), "mean": lambda *a: statistics.mean(a),
        "median": lambda *a: statistics.median(a), "stdev": lambda *a: statistics.stdev(a),
        "radians": math.radians, "degrees": math.degrees,
    }


def _pow(a, b):
    if abs(b) > MAX_EXP:
        raise ValueError(f"exponent is capped at {MAX_EXP}")
    return a ** b


def _prepare(expr):
    s = (expr or "").strip().lower().replace("×", "*").replace("÷", "/").replace("−", "-").replace("$", "")
    if not re.search(r"[a-z]\s*\(", s):                                   # no function calls: commas are thousands
        s = re.sub(r"(?<=\d),(?=\d{3}\b)", "", s)                        # 12,500 -> 12500
    s = s.replace("^", "**")
    s = re.sub(r"(\d+(?:\.\d+)?)\s*%\s*of\s*", r"(\1/100)*", s)          # 15% of 80
    s = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"(\1/100)", s)                   # 15%
    s = re.sub(r"(\d+|\))\s*!", r"factorial(\1)", s)                    # 5!
    s = re.sub(r"\bx\b", "*", s)                                          # 3 x 4
    return s


def evaluate(expr, deg=True):
    fns = _functions(deg)

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
            a, b = ev(node.left), ev(node.right)
            return _pow(a, b) if isinstance(node.op, ast.Pow) else _BIN[type(node.op)](a, b)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            return _UNARY[type(node.op)](ev(node.operand))
        if isinstance(node, ast.Name) and node.id in CONSTANTS:
            return CONSTANTS[node.id]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in fns and not node.keywords:
            return fns[node.func.id](*[ev(a) for a in node.args])
        raise ValueError("only numbers, + - * / ^ % ! ( ) and math functions are allowed")

    return ev(ast.parse(_prepare(expr), mode="eval"))


def _fmt(x):
    if isinstance(x, float):
        if x.is_integer() and abs(x) < 1e15:
            return f"{int(x):,}"
        return f"{x:,.10g}" if abs(x) < 1e15 else f"{x:.6e}"
    if isinstance(x, int) and abs(x) >= 1e21:
        return f"{x:.6e}"
    return f"{x:,}"


def calculate(expression, angle_unit=None):
    """Tool entry: returns 'expression = result' or a plain error. Trig is in degrees unless the angle
    unit says radians - or pi appears inside a trig call (cos(pi) means radians to everyone)."""
    if not angle_unit:
        angle_unit = "rad" if re.search(r"\b(a?sin|a?cos|a?tan)h?\s*\([^)]*\b(pi|tau)\b", (expression or "").lower()) else "deg"
    try:
        result = evaluate(expression, deg=angle_unit.lower().startswith("deg"))
        return f"{expression.strip()} = {_fmt(result)}"
    except ZeroDivisionError:
        return f"{expression.strip()}: can't divide by zero"
    except (ValueError, TypeError, SyntaxError, OverflowError, statistics.StatisticsError) as e:
        return f"Couldn't calculate '{expression.strip()}': {e}"
