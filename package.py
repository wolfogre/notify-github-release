import os
import shutil
from modulefinder import ModuleFinder


def main():
    temp_dir = "package_temp"
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    os.makedirs(temp_dir)

    for py in ["index.py", "notifier.py"]:
        src, dst = py, os.path.join(temp_dir, py)
        print("copy '%s' to '%s'" % (src, dst))
        shutil.copy(src, dst)

    print("analysing modules ...")
    finder = ModuleFinder()
    finder.run_script("index.py")

    module_paths = set()
    for name, mod in finder.modules.items():
        if mod.__path__ and "site-packages" in mod.__path__[0]:
            path = mod.__path__[0]
            while os.path.basename(os.path.dirname(path)) != "site-packages":
                path = os.path.dirname(path)
            if path not in module_paths:
                src, dst = path, os.path.join(temp_dir, os.path.basename(path))
                print("copy '%s' from '%s' to '%s'" % (name, src, dst))
                shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                module_paths.add(path)

    zip_file = "notify-github-release"
    print("zipping %s to %s.zip ..." % (temp_dir, zip_file))
    if os.path.exists(zip_file + ".zip"):
        os.remove(zip_file + ".zip")
    shutil.make_archive(zip_file, 'zip', temp_dir)

    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)

    print("done")


if __name__ == '__main__':
    main()

