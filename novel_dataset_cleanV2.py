import os
import json
import re
from tqdm import tqdm
import chardet
from pathlib import Path
import textwrap

class NovelDatasetGenerator:
    def __init__(self, input_dir, output_dir):
            self.input_dir = Path(input_dir)
            self.output_dir = Path(output_dir)
            self.genre = self.input_dir.name
            self.config = {
                'title_pattern': r'^(?:《)?([^》\n]{1,30})(?:》)?\s*作者[：:]',
                'author_pattern': r'作者[：:]\s*([^\n]+?)\s*\n',
                'chapter_pattern': r'(?:^|\n)(第[0-9一二三四五六七八九十百千万零]+[章回节][^\n]{1,50})',
                'outline_start': r'(?:内容简介|作品大纲)[：:]?\n',
                'min_content_length': 200,
                'chapter_summary_length': 100,
                'prompt_templates': {
                    'outline_request': "请生成【{genre}】类型的小说，小说的【主题大纲】是：{theme}，需要写出【{chapter_count}】章的长度，请给我每一章的小说章节大纲",
                    'content_request': "请根据我的小说章节大纲，帮我生成【{length}】字的小说章节内容：{outline}"
                }
            }

    def detect_encoding(self, file_path):
        with open(file_path, 'rb') as f:
            raw = f.read()
            return chardet.detect(raw)['encoding'] if chardet.detect(raw)['confidence'] > 0.75 else 'utf-8'

    def _build_dialogue_pair(self, prompt, content):
        return {
            "text": f"<s>{prompt}</s> <s>{content}</s>"
        }

    def _extract_summary(self, text):
            """更智能的摘要提取"""
            # 去除特殊符号和空白
            clean_text = re.sub(r'[　【】（）《》“”‘’…]', '', text.strip())
            # 找到第一个完整句子结尾
            sentence_end = re.search(r'[。！？…](?![^（）]*\))', clean_text)  # 排除括号内的标点
            if sentence_end:
                summary = clean_text[:sentence_end.end()]
                if len(summary) >= self.config['chapter_summary_length']:
                    return summary[:self.config['chapter_summary_length']] + '...'
                return summary
            return clean_text[:self.config['chapter_summary_length']] + '...'

    def _process_single_file(self, file_path):
            try:
                encoding = self.detect_encoding(file_path)
                with open(file_path, 'r', encoding=encoding, errors='replace') as f:
                    text = f.read()

                    # 提取元数据
                    meta = {
                        "genre": self.genre,
                        "title": self._extract_title(text) or file_path.stem,
                        "theme": self._extract_theme(text),
                    }

                    # 分割章节
                    chapters = self._split_chapters(text)
                    if not chapters:
                        return []

                    # 生成样本
                    samples = []
                    samples.append(self._generate_outline_prompt(meta, chapters))
                    samples.extend(self._generate_content_prompts(meta, chapters))

                    return samples
            except Exception as e:
                print(f"处理失败 {file_path}: {str(e)}")
                return []
    def _extract_title(self, text):
            """增强标题提取"""
            match = re.search(self.config['title_pattern'], text)
            return match.group(1).strip() if match else None

    def _extract_author(self, text):
                """增强作者提取"""
                match = re.search(self.config['author_pattern'], text)
                return match.group(1).strip() if match else "未知作者"
    def _clean_title(self, title):
            """清洗标题中的冗余信息"""
            # 移除卷信息（示例："卷一 血色风云 第一章 美女盟主" → "美女盟主"）
            return re.sub(r'^第?[卷篇]\s*\S+\s+', '', title).strip()
    def _process_chapters(self, meta, chapters):
        samples = []
        for chapter_num, (title, content) in enumerate(chapters, 1):
            # 跳过空内容
            if not content.strip():
                continue

            # 生成大纲条目
            outline = f"{chapter_num} {self._clean_title(title)}:{self._extract_summary(content)}"

            # 生成大纲请求
            outline_prompt = self.config['prompt_templates']['outline_request'].format(
                genre=meta['genre'],
                theme=meta['theme'],
                chapter_count=len(chapters)
            )
            samples.append(self._build_dialogue_pair(outline_prompt, outline))

            # 生成内容请求
            paragraphs = [p for p in re.split(r'\n{2,}', content) if p.strip()]
            for para in paragraphs:
                content_prompt = self.config['prompt_templates']['content_request'].format(
                    length=len(para),
                    outline=self._extract_summary(para)
                )
                samples.append(self._build_dialogue_pair(content_prompt, para))

        return samples
    def _split_chapters(self, text):
            """最终修正的章节分割方法"""
            # 增强正则表达式：兼容中文数字和阿拉伯数字
            chapter_re = re.compile(
                r'(?:^|\n)(第[0-9一二三四五六七八九十百千万零]+章)\s*([^\n]{1,50})',
                re.MULTILINE
            )

            # 移除所有番外和作品相关
            clean_text = re.sub(
                r'\n(作品相关|设定集|番外)[\s\S]+?\n(?=第[^\n]{1,10}章)',
                '\n', text
            )

            chapters = []
            matches = list(chapter_re.finditer(clean_text))

            # 添加调试日志
            print(f"找到{len(matches)}个章节标题")
            for match in matches[:3]:
                print(f"示例标题：{match.group()}")

            for i in range(len(matches)):
                # 获取当前章节信息
                title_num = matches[i].group(1)
                title_text = matches[i].group(2).strip()
                full_title = f"{title_num} {title_text}"

                # 获取内容范围
                start = matches[i].end()
                end = matches[i+1].start() if i+1 < len(matches) else len(clean_text)

                # 提取并清理内容
                content = clean_text[start:end].strip()
                content = re.sub(r'\n{3,}', '\n\n', content)

                if len(content) >= self.config['min_content_length']:
                    chapters.append((full_title, content))
                    print(f"有效章节：{full_title} | 内容长度：{len(content)}")
                else:
                    print(f"跳过短章节：{full_title} | 内容长度：{len(content)}")

            return chapters
    def _num_to_chinese(self, num_str):
            """将数字编号转换为中文数字（用于过滤重复标题）"""
            num_map = {
                '1': '一', '2': '二', '3': '三', '4': '四', '5': '五',
                '6': '六', '7': '七', '8': '八', '9': '九', '10': '十'
            }
            return ''.join(num_map.get(c, c) for c in num_str if c.isdigit())
    def _extract_theme(self, text):
            """精确提取内容简介"""
            # 找到简介结束位置（遇到第一个章节或空两行）
            theme_match = re.search(
                r'(?:内容简介|作品大纲)[：:]?\n([\s\S]+?)(?=\n{2,}[第卷]|\n第[^\n]{1,10}章|$)',
                text
            )
            return theme_match.group(1).strip()[:500] + '...' if theme_match else ""
    def _generate_outline_prompt(self, meta, chapters):
            """生成大纲样本"""
            outline_items = []
            for idx, (title, content) in enumerate(chapters, 1):
                summary = self._extract_summary(content)
                outline_items.append(f"第{idx}章 {title}: {summary}")

            return self._build_dialogue_pair(
                self.config['prompt_templates']['outline_request'].format(
                    genre=meta['genre'],
                    theme=meta['theme'],
                    chapter_count=len(chapters)
                ),
                "\n".join(outline_items)
            )
    def _generate_content_prompts(self, meta, chapters):
            """生成内容样本"""
            samples = []
            for title, content in chapters:
                # 提取章节前100字作为大纲
                outline = self._extract_summary(content)

                samples.append(
                    self._build_dialogue_pair(
                        self.config['prompt_templates']['content_request'].format(
                            length=len(content),
                            outline=f"{title}: {outline}"
                        ),
                        content
                    )
                )
            return samples
    def _process_complete_chapter(self, samples, meta, current_content, all_outlines, current_title):
            """修复后的完整章节处理"""
            try:
                # 生成大纲请求
                if all_outlines:
                    outline_prompt = self.config['prompt_templates']['outline_request'].format(
                        genre=meta['genre'],
                        theme=meta['theme'],
                        chapter_count=len(all_outlines)
                    )
                    outline_response = "\n".join(all_outlines)
                    samples.append(self._build_dialogue_pair(outline_prompt, outline_response))

                # 生成内容请求
                full_content = '\n'.join(current_content).strip()
                if len(full_content) >= self.config['min_content_length']:
                    paragraphs = [p for p in re.split(r'\n{2,}', full_content) if p.strip()]
                    for para in paragraphs:
                        if all_outlines:
                            outline_part = all_outlines[0].split(':', 1)[-1].strip()
                        else:
                            outline_part = self._extract_summary(para)

                        content_prompt = self.config['prompt_templates']['content_request'].format(
                            length=len(para),
                            outline=outline_part
                        )
                        samples.append(self._build_dialogue_pair(content_prompt, para))
            except Exception as e:
                print(f"章节处理异常：{str(e)}")

    def process_folder(self):
        all_samples = []
        txt_files = list(self.input_dir.glob("*.txt"))
        for file_path in tqdm(txt_files, desc=f"处理 {self.genre} 类别"):
            all_samples.extend(self._process_single_file(file_path))
        return all_samples

    def run(self):
        self.output_dir.mkdir(exist_ok=True, parents=True)
        output_file = self.output_dir / f"{self.genre}_dataset.jsonl"

        samples = self.process_folder()
        with open(output_file, 'w', encoding='utf-8') as f:
            for sample in tqdm(samples, desc=f"写入 {self.genre} 数据"):
                f.write(json.dumps(sample, ensure_ascii=False) + '\n')

if __name__ == "__main__":
    input_base = "./raw_novels"
    output_dir = "./structured_dataset"

    genre_dirs = [d for d in Path(input_base).iterdir() if d.is_dir()]
    for genre_dir in tqdm(genre_dirs, desc="处理总进度"):
        processor = NovelDatasetGenerator(genre_dir, output_dir)
        processor.run()
