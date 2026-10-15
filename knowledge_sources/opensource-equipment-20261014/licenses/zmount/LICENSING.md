# Licensing / ライセンス

Copyright and similar rights that this project can license in its data are offered under the **Creative Commons Attribution 4.0 International (CC BY 4.0)** license. Code, schemas, and related material are offered under the **MIT License**. Use the scope below rather than inferring a license from a file extension.

本プロジェクトがデータについて保有するか許諾権限を持つ著作権その他これに類する権利には、**Creative Commons Attribution 4.0 International（CC BY 4.0）**を適用します。
ソースコード、JSON Schema、テスト、ツール、設定、ドキュメントなどは、**MIT License**で提供します。
ライセンスの適用範囲は、ファイルの拡張子ではなく、次の表で確認してください。

## Scope / 適用範囲

| Material / 対象 | License / ライセンス |
| --- | --- |
| `data/**/*.json` | [CC BY 4.0](LICENSES/CC-BY-4.0.txt) |
| `research/results/**/*.json` | [CC BY 4.0](LICENSES/CC-BY-4.0.txt) |
| `dist/z-mount-lenses.full.json` | [CC BY 4.0](LICENSES/CC-BY-4.0.txt) |
| `dist/z-mount-lenses.light.json` | [CC BY 4.0](LICENSES/CC-BY-4.0.txt) |
| `dist/z-mount-adapters.full.json` | [CC BY 4.0](LICENSES/CC-BY-4.0.txt) |
| `PRODUCTS.md` | [CC BY 4.0](LICENSES/CC-BY-4.0.txt) |
| Source code, schemas, tests, tools, configuration, README, CONTRIBUTING, and documentation / ソースコード、JSON Schema、テスト、ツール、設定、README、CONTRIBUTING、ドキュメント | [MIT](LICENSES/MIT.txt) |

`REUSE.toml` is the machine-readable source of truth for file-level scope. The root `license` (`CC-BY-4.0`) and `licenseUrl` fields in each distribution also identify the data license. Canonical records and research results do not repeat identical license fields; `data/LICENSE`, `research/LICENSE`, and this document are human-readable guides.

`REUSE.toml`に、ファイル単位の適用範囲を機械可読な形式で定義しています。
各配布データでは、ルートの`license`（`CC-BY-4.0`）と`licenseUrl`もデータライセンスを示します。
収録製品データと調査結果データには同じライセンス情報を繰り返さず、`data/LICENSE`、`research/LICENSE`、この文書で人向けに案内しています。

## Recommended attribution / 推奨クレジット

For unmodified use:

そのまま利用する場合：

> Z Mount Product Database, Katsura Iwamoto, CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/), https://github.com/KatsuraIwamoto/z-mount-product-database

When publishing modified data, retain the attribution above and indicate that changes were made.

変更したデータを公開する場合は、上記に加えて変更したことを明記してください。

## License texts / ライセンス本文

`LICENSES/MIT.txt` contains the standard English MIT License text. `LICENSES/CC-BY-4.0.txt` contains the original English CC BY 4.0 text. Creative Commons also publishes an [official Japanese legal code](https://creativecommons.org/licenses/by/4.0/legalcode.ja).

`LICENSES/MIT.txt`には、MIT Licenseの標準英語本文を収録しています。
`LICENSES/CC-BY-4.0.txt`には、CC BY 4.0の英語原文を収録しています。
Creative Commonsは、[公式日本語リーガル・コード](https://creativecommons.org/licenses/by/4.0/legalcode.ja)も公開しています。

## Schemas and data / JSON Schemaとデータ

The `SPDX-FileCopyrightText` and `SPDX-License-Identifier: MIT` lines in each schema's `$comment` identify the copyright and license of that schema file itself. They do not change the license of JSON data validated by the schema to MIT.

各JSON Schemaの`$comment`にある`SPDX-FileCopyrightText`と`SPDX-License-Identifier: MIT`は、そのJSON Schemaファイル自身の著作権とライセンスを示します。
JSON Schemaで検証する調査結果データ、収録製品データ、レジストリ、配布データのライセンスをMIT Licenseへ変更するものではありません。

## Rights covered by CC BY 4.0 / CC BY 4.0の対象となる権利

CC BY 4.0 applies only to copyright and similar rights, including database rights where applicable, that this project owns or has authority to license. The project does not claim copyright in factual product specifications merely by collecting them. When a use does not require permission under applicable law, CC BY 4.0 does not impose conditions on that use.

CC BY 4.0が適用されるのは、該当する場合のデータベース権を含め、本プロジェクトが保有するか許諾権限を持つ著作権その他これに類する権利だけです。
製品仕様という事実を収集したことだけを理由に、その事実自体の著作権を主張するものではありません。
適用法上、許諾を必要としない利用にCC BY 4.0の条件は課されません。

## Trademarks, other third-party rights, and no affiliation / 商標、第三者の権利、メーカー等との関係

> [!IMPORTANT]
> Patent and trademark rights are not licensed under CC BY 4.0. Manufacturer names, brand names, product names, logos, and other marks may be trademarks or registered trademarks of their respective owners and remain subject to third-party rights.
>
> CC BY 4.0では、特許権と商標権は許諾されません。
> メーカー名、ブランド名、製品名、ロゴその他の標章は、各権利者の商標または登録商標である場合があり、第三者の権利の対象です。

Names and marks in the database are used only to identify products and information sources. This is an independent project and is not affiliated with, authorized by, sponsored by, or endorsed by Nikon Corporation or any other manufacturer or rights holder. Links to official pages do not imply such a relationship. No rights in third-party pages or other third-party material are granted by this project.

データベース内の名称と標章は、製品と情報源を特定する目的でのみ使用します。
Z Mount Product Databaseは独立したプロジェクトです。
Nikon Corporationを含むメーカーや権利者との提携関係になく、公認、後援、推奨を受けたものでもありません。
公式ページへのリンクも、そのような関係を意味しません。
本プロジェクトは、リンク先ページその他の第三者素材に関する権利を許諾しません。
