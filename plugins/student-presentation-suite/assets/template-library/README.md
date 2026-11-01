# Portable student-design references

This directory is shipped inside the plugin. Runtime paths are relative to
`catalog.json`; another computer needs no source drive or original PPTX files.

Contents: 99 compressed editable-object layout recipes (98 common templates and
the supplied blue scholarship-defense reference), plus all supplied common
previews and the featured reference's 33 page previews. Preview-only entries are
kept when there is no matching supported OOXML source. Counts and checksums in
the catalog are authoritative.

Recipes record canvas size, object order and geometry, text styling, colors,
groups, table structure, image/chart replacement slots and master/layout/theme
inheritance. Read a selected page with `scripts/template_library.py recipe
award-blue --slide 7`. Rebuild separate editable objects from task material;
these are references, not original template packages or final slide content.
Fonts and original image files are not embedded. Coordinate values inside groups
remain relative to their recorded parent transform.

The repository owner supplied the “校园PPT研究所-蓝色国家奖学金答辩PPT” and
“无门槛领取-100套大学生常用PPT模板” collections. Source names and SHA-256 values
are recorded without machine-specific paths. Supplied preview attribution is
retained. These third-party design examples are not represented as suite-owned
work or relicensed under the code's MIT license; original attribution and terms
remain applicable. No redistribution license text accompanied the supplied
collections. Example names, schools, achievements, photos, promotional copy,
word limits and speaking-time advice are not facts or instructions for a task.

Rebuild, when the owner has the source collections available:

```bash
python scripts/build_template_references.py --template-dir <original-pptx-dir> --preview-dir <original-preview-dir> --featured <featured.pptx> --featured-previews <rendered-jpg-dir> --output-dir <fresh-library-dir>
```

The builder never executes template text or copies PPTX/font binaries. Use the
suite-owned render facade for featured JPEG previews (prefix `award`, matching
`award-01.jpg` etc.). Ordinary production searches the shipped catalog, not the
developer's original folders. See [template workflow](../../references/template-workflow.md) for use.
