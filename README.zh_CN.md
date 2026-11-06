# dsh-desktop-linux-copr

[English](README.md) | 简体中文

这是 [dsh-desktop-linux](https://github.com/ffyfox/dsh-desktop-linux) 的 Fedora
打包仓库，在 COPR 中基于上游项目发布的预编译 RPM 构建。

本仓库是**重新打包（repack），不是从源码构建**。上游项目构建的是一个 Electron
应用，捆绑了 Node.js 与 Python 运行时，并为 `x86_64` 和 `aarch64` 发布未签名的
RPM。本仓库负责校验这些 RPM，并为它们补上适合 Fedora 的元数据。

* COPR 项目：`anise0x7c/DeepSeekHarnessDesktop`
* 包名：`deepseek-harness`（与上游一致）
* COPR 构建方式：SCM Git + `make_srpm`

## 目录结构

| 路径 | 用途 |
| --- | --- |
| `packaging/release.json` | 唯一版本来源：上游 tag/commit、版本、release、各架构资产的校验和、许可证表达式、运行时依赖 |
| `packaging/deepseek-harness.spec.tmpl` | spec 模板；与版本相关的值会被替换 |
| `deepseek-harness.spec` | 生成的 spec，提交进仓库，便于 COPR 和审查者看到实际构建的内容 |
| `.copr/Makefile` | COPR `make_srpm` 调用的 `srpm` 目标 |
| `scripts/make-spec.py` | 由清单重新生成或校验 spec |
| `scripts/make-srpm.py` | 下载、校验两个上游 RPM 并打包成一个 SRPM |
| `scripts/update-release.py` | 发现更新的上游 release 并刷新清单/spec |
| `scripts/check-rpmlint.py` | 遇到未列入 `packaging/rpmlint-exceptions.txt` 的 rpmlint 结果时失败 |
| `.github/workflows/` | 上游更新 PR 与四目标打包 CI |
| `docs/deployment.md` | COPR 与 webhook 的分步配置说明 |

不要手工编辑 `deepseek-harness.spec`：请修改清单（或模板），然后运行
`python3 scripts/make-spec.py`。CI 会拒绝过期的 spec。

## 本地流程

```console
$ python3 -m unittest discover -s tests -v     # 单元测试
$ python3 scripts/make-spec.py --check         # spec 与清单一致
$ python3 scripts/make-srpm.py                 # 下载 + 校验 + 构建 SRPM
$ python3 scripts/update-release.py --check    # 上游是否有更新的 release？
```

`make-srpm.py` 会把下载的 RPM 缓存到 `.work/cache/`，并在每次运行时重新校验其
大小和 SHA-256。如果 RPM 头与清单不符，或已发布资产与记录的校验和不一致，它会
拒绝构建。

若想在没有 COPR 的情况下检验 spec，可在本地重建 SRPM：

```console
$ rpmbuild --rebuild \
    --define "_topdir $PWD/.work/rebuild" \
    --define "_tmppath $PWD/.work/rebuild/tmp" \
    dist/*.src.rpm
```

生成的二进制 RPM 的 payload 必须与上游归档逐字节一致；spec 会在 `%install`
阶段再次检查。

## 打包决策

* 应用保留在 `/opt/DeepSeek Harness`（注意路径中的空格），这样从上游包升级时
  仍然可用，同时私有的 Node.js 和 Python 运行时保持自包含。
* `/usr/bin/deepseek-harness` 是本包拥有的符号链接。上游的 `%postun` 会无条件
  删除该路径，这会破坏升级，因此本包在 `%posttrans` 中修复它。
* `chrome-sandbox` 以 `0755` 安装，不设 setuid。应用使用非特权用户命名空间；
  spec 从不注入 `--no-sandbox`。
* 自动依赖生成已禁用（`AutoReqProv: no`），运行时依赖显式列出，避免捆绑的私有
  soname 泄漏到发行版的依赖图中。
* `__os_install_post` 与 `__arch_install_post` 已禁用：payload 不得被 strip、
  字节编译、赋予新的 build-id 或硬链接。
* 上游归档中的 `/usr/lib/.build-id` 链接不会安装；除 desktop 条目、图标和启动器
  符号链接外，本包不拥有自身目录树之外的任何内容。
* 许可证表达式是对 payload 审计后的聚合结果（Electron、Chromium、捆绑的 npm 与
  Python 包、字体），而不只是上游 RPM 头里的 MIT。参见
  `packaging/release.json` → `audit`。

## 更新

一个定时的 GitHub Actions workflow 每天检查上游，并针对 `main` 创建（或更新）
一个 pull request。工具会跟随 annotated tag 解析到 commit，接受 alpha/beta/rc
版本，使用 RPM 自身的版本排序比较版本，并要求双架构齐全、GitHub 报告 SHA-256
digest、RPM 头匹配且 release 为数字。任何它无法理解的情况都会让该次运行失败，
而不是猜测。

合并 PR 后，COPR 会通过其原生 GitHub webhook 触发构建。

## 限制

* 上游 RPM 未签名；本仓库通过 GitHub release API 提供的 SHA-256 校验它们，而
  不是通过签名。
* aarch64 包会在 CI 中构建并做冒烟测试，但尚未在此处的 aarch64 硬件上实际运行
  GUI。
* 这是 COPR/WIP 包，不属于 Fedora。
