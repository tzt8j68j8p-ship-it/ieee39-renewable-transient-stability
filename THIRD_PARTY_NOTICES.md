# Third-party notices

This project is distributed under GPL-3.0-or-later. The full license is in [LICENSE](LICENSE).

## ANDES

ANDES 2.0.0 is distributed under GPL-3.0-or-later according to its distribution metadata.
Its original authorship and copyright notices remain applicable.
Upstream project: [CURENT/andes](https://github.com/CURENT/andes).

The upstream ANDES copyright and license notice is retained here; the root
`LICENSE` contains the standard GNU GPL v3 text supplied by GitHub's license API.

> ANDES: Python Software for Symbolic Power System Modeling and Numerical Analysis
>
> Copyright (c) 2015-2026 Hantao Cui
>
> This program is free software; you can redistribute it and/or modify
> it under the terms of the GNU General Public License as published by
> the Free Software Foundation; either version 3 of the License, or
> (at your option) any later version.
>
> This program is distributed in the hope that it will be useful,
> but WITHOUT ANY WARRANTY; without even the implied warranty of
> MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
> GNU General Public License for more details.
>
> A copy of the GNU General Public License is included in LICENSE.
> For further information, see <http://www.gnu.org/licenses/>.

The official IEEE39 workbook is an unchanged copy of the bundled ANDES case
`andes/cases/ieee39/ieee39_full.xlsx`. Source version, SHA256 and expected model counts
are recorded in [cases/manifest.json](cases/manifest.json).

## Adapted IEEE39 and renewable templates

The adapted synchronous baseline and Bus37 renewable pilot are author-maintained
IEEE39 derivatives, bundled under `cases/renewable/sources/` with their SHA256 values.
The generic GFL construction pattern originated in an author-maintained prototype;
it preserves the underlying ANDES model definitions and upstream IEEE39 attribution.

The main renewable models use ANDES REGCP1, PLL2 and REECB1. Their ratings,
replacement mappings and deterministic workbook hashes are documented in
[model provenance](docs/model_provenance.md). No private project directory is
required to run the published fault, CCT or comparison entry points.

The runner, metrics and integer-grid binary-search flow were refactored from
author-maintained prototypes. Those prototypes are not imported at runtime.
