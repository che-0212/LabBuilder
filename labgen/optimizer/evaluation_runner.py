"""
运行 USD 生成、渲染与评估的封装
"""

import json
import subprocess
import logging
from pathlib import Path
from typing import Dict, Optional

from labgen.optimizer.config import SCRIPT_PATHS

logger = logging.getLogger(__name__)


class EvaluationRunner:
    """负责执行完整的评估流水线"""

    def __init__(
        self,
        usd_script: Path = SCRIPT_PATHS["usd_generator"],
        renderer_script: Path = SCRIPT_PATHS["renderer"],
        evaluator_script: Path = SCRIPT_PATHS["evaluator"],
        images_dir: Path = SCRIPT_PATHS["images_dir"],
    ) -> None:
        self.usd_script = usd_script
        self.renderer_script = renderer_script
        self.evaluator_script = evaluator_script
        self.images_dir = images_dir

        for script in [self.usd_script, self.renderer_script, self.evaluator_script]:
            if not script.exists():
                raise FileNotFoundError(f"脚本不存在: {script}")

    def _run_cmd(
        self,
        command: list[str],
        cwd: Optional[Path] = None,
        env: Optional[dict] = None,
        stdout_enabled: bool = True,
    ) -> None:
        logger.info("执行命令: %s", " ".join(str(x) for x in command))
        capture_output = stdout_enabled
        process = subprocess.Popen(
            command,
            cwd=str(cwd) if cwd else None,
            env=env,
            stdout=subprocess.PIPE if capture_output else None,
            stderr=subprocess.STDOUT if capture_output else None,
            text=True,
            bufsize=1,
        )

        captured_lines: list[str] = []
        if capture_output and process.stdout:
            for line in process.stdout:
                captured_lines.append(line)
                logger.info(line.rstrip())

        return_code = process.wait()
        if return_code != 0:
            if capture_output:
                output_text = "".join(captured_lines)
            else:
                output_text = "<no output captured>"
            raise RuntimeError(
                f"命令执行失败: {' '.join(command)} (return code {return_code})\n输出:\n{output_text}"
            )

    def _prepare_images_dir(self) -> None:
        if self.images_dir.exists():
            for file in self.images_dir.glob("view_*.png"):
                try:
                    file.unlink()
                except OSError:
                    pass
        else:
            self.images_dir.mkdir(parents=True, exist_ok=True)

    def generate_usd(self, layout_path: Path, usd_output: Optional[Path] = None) -> Path:
        layout_path = layout_path.resolve()
        usd_output = usd_output or layout_path.with_suffix(".usd")

        logger.info("正在生成 USD 文件...")
        command = ["bash", str(self.usd_script), str(layout_path), str(usd_output)]
        # 禁用输出以避免日志过长
        self._run_cmd(command, cwd=self.usd_script.parent, stdout_enabled=False)
        if not usd_output.exists():
            raise FileNotFoundError(f"USD 文件未生成: {usd_output}")
        logger.info("✓ USD 文件生成完成: %s", usd_output.name)
        return usd_output

    def render_views(self, usd_path: Path) -> Path:
        self._prepare_images_dir()
        logger.info("正在渲染视图...")
        # 使用 conda run 来激活 isaac 环境并运行脚本
        command = ["conda", "run", "-n", "isaac", "bash", str(self.renderer_script), str(usd_path)]
        # 禁用输出以避免日志过长
        self._run_cmd(command, cwd=self.renderer_script.parent, stdout_enabled=False)

        images = list(self.images_dir.glob("view_*.png"))
        if len(images) < 5:
            raise RuntimeError("渲染结果不足 5 张视图，可能渲染失败")
        logger.info("✓ 渲染完成，生成 %d 张视图", len(images))
        return self.images_dir

    def evaluate(
        self,
        layout_path: Path,
        protocol_path: Path,
        evaluation_output_dir: Path,
        skip_semantic: bool = False,
    ) -> Dict:
        evaluation_output_dir.mkdir(parents=True, exist_ok=True)

        command = [
            "bash",
            str(self.evaluator_script),
            str(layout_path),
            str(protocol_path),
            str(evaluation_output_dir),
        ]
        
        # 如果跳过语义评估，添加参数
        if skip_semantic:
            command.append("--skip-semantic")
        
        self._run_cmd(command, cwd=self.evaluator_script.parent)

        report_files = sorted(evaluation_output_dir.glob("*_evaluation_report.json"))
        if not report_files:
            raise FileNotFoundError(
                f"在 {evaluation_output_dir} 中未找到评估报告 JSON"
            )
        report_path = report_files[-1]

        with report_path.open("r", encoding="utf-8") as f:
            report = json.load(f)
        return report

    def run_full_pipeline(
        self,
        layout_path: Path,
        protocol_path: Path,
        working_dir: Path,
        skip_semantic: bool = False,
    ) -> Dict:
        """
        运行完整的评估流水线
        
        Args:
            skip_semantic: 是否跳过语义评估（跳过USD生成和渲染）
        """
        working_dir.mkdir(parents=True, exist_ok=True)
        layout_path = layout_path.resolve()

        if skip_semantic:
            # 快速模式：只运行物理评估（70分），不生成USD和渲染
            logger.info("快速模式：跳过USD生成和渲染，只评估物理约束")
            report = self.evaluate(layout_path, protocol_path, working_dir / "evaluation",
                                  skip_semantic=True)
        else:
            # 完整模式：USD + 渲染 + 完整评估（100分）
            usd_path = self.generate_usd(layout_path)
            self.render_views(usd_path)
            report = self.evaluate(layout_path, protocol_path, working_dir / "evaluation",
                                  skip_semantic=False)
        
        return report


