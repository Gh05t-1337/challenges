#!/bin/env python3

import subprocess
import textwrap
import argparse
import pyastyle
import pathlib
import random
import shutil
import jinja2
import base64
import black
import shlex
import glob
import sys
import os
import re

class ChallengeRandom(random.Random):
    pass

def layout_text(text):
    return "\n".join(f'puts("{line}");' for line in textwrap.wrap(textwrap.dedent(text), width=120))

@jinja2.pass_context
def layout_text_walkthrough(context, text):
    return layout_text(text) if not context.get("walkthrough") or context.get("challenge.walkthrough") else "\n"

def render(template, seed):
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(template.parents))
    env.filters.update({ "layout_text": layout_text, "layout_text_walkthrough": layout_text_walkthrough })
    rendered = env.get_template(template.name).render(random=ChallengeRandom(seed), trim_blocks=True, lstrip_blocks=True)
    try:
        if ".py" in template.suffixes or "python" in rendered.splitlines()[0]:
            return black.format_str(rendered, mode=black.FileMode(line_length=120))
        elif ".c" in template.suffixes:
            return re.sub("\n{2,}", "\n\n", pyastyle.format(rendered, "--style=allman"))
    except black.parsing.InvalidInput as e:
        print(f"WARNING: template {template} does not format properly: {e}")
    return rendered

def render_challenge(template_dir, seed, output_dir=None):
    rendered_dir = output_dir or pathlib.Path(f"/tmp/pwncollege-{template_dir.name}-{os.urandom(4).hex()}")
    shutil.copytree(template_dir, rendered_dir)
    if (rendered_dir/"challenge").exists() and not (dockerfile_path := rendered_dir/"challenge/Dockerfile").exists():
        dockerfile_path.write_text(render(pathlib.Path(__file__).parent/"base_templates/default-dockerfile.j2", seed))

    for j2_file in ( f.relative_to(template_dir) for f in template_dir.rglob("*.j2") ):
        (rendered_dir/j2_file).with_suffix('').write_text(render(template_dir/j2_file, seed))
        (rendered_dir/j2_file).with_suffix('').chmod((template_dir/j2_file).stat().st_mode)
        (rendered_dir/j2_file).unlink()

    return rendered_dir

def test_challenge(challenge_dir, image_name, seed):
    temp_flag = pathlib.Path(challenge_dir / "flag")
    temp_flag.write_text("pwn.college{"+base64.b64encode(os.urandom(40)).decode()+"}")

    try:
        for test_file in glob.glob(str(challenge_dir/"test*/test_*")):
            container = subprocess.check_output([
                "docker", "run", "--rm", "-id",
                "--name", f"""{image_name}-{re.sub("[^a-zA-Z0-9-]", "", os.path.basename(test_file))}""",
                "-v", f"{challenge_dir}:{challenge_dir}:ro", "-v", f"{temp_flag}:/flag:ro",
                image_name, "sh", "-c", "read forever"
            ]).decode().strip()
            subprocess.check_call(["docker", "exec", container, "sh", "-c", "[ ! -e /challenge/.init ] || /challenge/.init"])
            subprocess.check_call([
                "docker", "exec", "-u", "1000:1000", "-e", f"FLAG={temp_flag.read_text()}", "-e", f"SEED={seed}", container, test_file
            ])
            print(f"PASSED: {test_file}")
            subprocess.check_output(["docker", "kill", container])
    except subprocess.CalledProcessError as e:
        print(f"FAILED: {shlex.join(e.cmd)}")
        return False
    return True

def main():
    parser = argparse.ArgumentParser(description="Render challenge templates")
    parser.add_argument("challenge", help="Challenge directory to build/test", type=pathlib.Path)
    parser.add_argument("--output-dir", help="Output file or directory", type=pathlib.Path)
    parser.add_argument("--render-only", action="store_true", help="Don't test, build, or tag.")
    parser.add_argument("--seed", action="store", help="The random seed for templating", default=random.randrange(2**64), type=int)
    args = parser.parse_args()

    if args.challenge.is_file():
        print(render(args.challenge, seed=args.seed))
        return 0

    rendered_dir = render_challenge(args.challenge, args.seed, output_dir=args.output_dir)
    print(f"Rendered to: {rendered_dir}")
    subprocess.check_call(["docker", "build", "-t", rendered_dir.name, rendered_dir/"challenge"])
    if not args.render_only and not test_challenge(rendered_dir, rendered_dir.name, args.seed):
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
