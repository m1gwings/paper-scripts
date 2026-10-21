import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE / 'templates/latex/papermacros.sty'


@unittest.skipUnless(shutil.which('latexmk'), 'latexmk is not installed')
class MacroCompilationTest(unittest.TestCase):
    def compile(self, root):
        result = subprocess.run(['latexmk', '-norc', '-pdf', '-no-shell-escape',
                                 '-interaction=nonstopmode', '-halt-on-error', 'main.tex'],
                                cwd=root, capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout[-4500:] + result.stderr[-1500:])
        pdf = root / 'main.pdf'
        self.assertTrue(pdf.read_bytes().startswith(b'%PDF'))
        self.assertIsNotNone(shutil.which('pdftotext'), 'Install poppler-utils for rendering assertions')
        return subprocess.check_output(['pdftotext', '-layout', str(pdf), '-'], text=True)

    def test_all_starters_compile_with_the_preview_command(self):
        for kind in ('paper', 'poster', 'slides'):
            with self.subTest(profile=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                subprocess.run(['git', 'init', '-q', str(root)], check=True)
                result = subprocess.run(['bash', str(SOURCE / 'paper'), 'init',
                                         *(() if kind == 'paper' else ('--' + kind,))],
                                        cwd=root, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                preview = subprocess.run(['python3', str(SOURCE / 'lib/preview.py')],
                                         cwd=root, capture_output=True, text=True, timeout=120)
                self.assertEqual(preview.returncode, 0, preview.stdout[-3000:] + preview.stderr)
                self.assertTrue((root / '.paper-preview/paper.pdf').read_bytes().startswith(b'%PDF'))

    def test_review_modes_have_correct_strikethrough_text_and_math_semantics(self):
        for profile in ('paper', 'slides', 'poster'):
            for mode in ('visible', 'applied', 'reverted'):
                with self.subTest(profile=profile, mode=mode), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    shutil.copyfile(PACKAGE, root / 'papermacros.sty')
                    is_paper = profile == 'paper'
                    preamble = r'\documentclass{article}' if is_paper else r'\documentclass{beamer}'
                    if profile == 'poster':
                        preamble += r'\usepackage[size=a1,scale=1.0]{beamerposter}'
                    preamble += ('\n' + r'\usepackage[profile=' + profile +
                                 ',review=' + mode + r']{papermacros}' + '\n')
                    preamble += r'''
\usepackage{natbib}
\usepackage{hyperref}
\makeatletter
\@ifundefined{AgentsIns}{\errmessage{Agent API missing}}{}
\@ifundefined{CodexIns}{}{\errmessage{Obsolete Codex API leaked}}
\@ifundefined{CMInline}{}{\errmessage{Obsolete Inline API leaked}}
\@ifundefined{AgentDelBlock}{}{\errmessage{Obsolete deletion API leaked}}
\@ifundefined{CMDelBlock}{}{\errmessage{Obsolete deletion API leaked}}
\@ifundefined{MMDelBlock}{}{\errmessage{Obsolete deletion API leaked}}
\@ifundefined{AMMDelBlock}{}{\errmessage{Obsolete deletion API leaked}}
\@ifundefined{DADelBlock}{}{\errmessage{Obsolete deletion API leaked}}
\@ifundefined{GGDelBlock}{}{\errmessage{Obsolete deletion API leaked}}
\@ifundefined{RebuttalDelBlock}{}{\errmessage{Obsolete deletion API leaked}}
\makeatother
\begin{document}
'''
                    body = r'''
\section{Test}\label{sec:test}
\AgentsDel{DELETEDWORD \ref{sec:test} \citep{example}}
\AgentsIns{INSERTEDWORD}
\par\AgentIns{COMPATADD} \AgentDel{COMPATDROP}\par
\CMIns{Author insertion.}\MMDel{Author deletion.}
$\Reals,\Reals[0],\Prob(A),\vec{x},\norm*{x},\AgentsDel{x^2}\AgentsIns{y^2}$.
\wp a statement.
\[\AgentsReplaceMath{a+b}{c+d}\]
\ifcommentsapplied\else
\AgentsDel{PARAGRAPHOLD}
\[\AgentsDel{u+v=w.}\]
\fi
\Agents{REVIEWNOTE}
'''
                    if is_paper:
                        body += r'''\begin{align*}
{\AgentsDel{a}}&{\AgentsDel{=b}}\\
{\AgentsDel{c}}&{\AgentsDel{=d}}
\end{align*}
'''
                    named_notes = r'\Agents[GPT-6 Astra]{NAMEDNOTE}\AgentsOut[GPT-6 Sol]{OUTSIDENOTE}'
                    if not is_paper:
                        body = r'\begin{frame}{Review}' + body + r'\end{frame}'
                        body += r'\begin{frame}{Model comments}' + named_notes + r'\end{frame}'
                    else:
                        body += named_notes
                    bibliography = r'''
\begin{thebibliography}{1}
\bibitem[Author(2026)]{example} Author. Example reference.
\end{thebibliography}
'''
                    if not is_paper:
                        bibliography = r'\begin{frame}{References}' + bibliography + r'\end{frame}'
                    (root / 'main.tex').write_text(preamble + body + bibliography + r'\end{document}')
                    text = self.compile(root)
                    self.assertEqual('INSERTEDWORD' in text, mode != 'reverted')
                    self.assertEqual('DELETEDWORD' in text, mode != 'applied')
                    self.assertEqual('COMPATADD' in text, mode != 'reverted')
                    self.assertEqual('COMPATDROP' in text, mode != 'applied')
                    self.assertEqual('PARAGRAPHOLD' in text, mode != 'applied')
                    self.assertEqual('REVIEWNOTE' in text, mode == 'visible')
                    for token in ('GPT-6 Astra', 'GPT-6 Sol', 'NAMEDNOTE', 'OUTSIDENOTE'):
                        self.assertEqual(token in text, mode == 'visible', token)
                    if mode == 'visible':
                        self.assertIn('Agents (AG)', text)
                        self.assertIn('GPT-6 Astra (AG)', text)

    def test_optional_comment_names_are_consumed_in_pdf_bookmarks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copyfile(PACKAGE, root / 'papermacros.sty')
            (root / 'main.tex').write_text(r'''\documentclass{article}
\usepackage{papermacros}
\usepackage{hyperref}
\begin{document}
\pdfbookmark{Heading\Agents[GPT-6 Astra]{HIDDENCOMMENT}\Agents{DEFAULTCOMMENT}\AgentsOut[GPT-6 Sol]{OUTCOMMENT}\AgentsOut{DEFAULTNOTE}}{test}
Visible body.
\end{document}''')
            self.compile(root)
            bookmarks = (root / 'main.out').read_text()
            self.assertIn(r'\000H\000e\000a\000d\000i\000n\000g', bookmarks)
            self.assertNotIn(r'\000[', bookmarks)
            self.assertNotIn(r'\000G\000P\000T', bookmarks)
            self.assertNotIn(r'\000C\000O\000M\000M\000E\000N\000T', bookmarks)

    def test_applied_deletion_does_not_execute_deleted_invalid_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copyfile(PACKAGE, root / 'papermacros.sty')
            (root / 'main.tex').write_text(r'''\documentclass{article}
\usepackage[review=applied]{papermacros}
\begin{document}
\AgentsDel{\UndefinedDeletedCommand}
\AgentsIns{Kept text.}
\end{document}''')
            self.assertIn('Kept text.', self.compile(root))

    def test_revisions_in_headings_and_captions_survive_auxiliary_file_roundtrip(self):
        for mode in ('visible', 'applied', 'reverted'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                shutil.copyfile(PACKAGE, root / 'papermacros.sty')
                (root / 'main.tex').write_text(
                    r'\documentclass{article}\usepackage[review=' + mode + r''']{papermacros}
\usepackage{hyperref}
\begin{document}
\tableofcontents
\listoffigures
\section{\AgentsDel{OLDHEADING}\AgentsIns{NEWHEADING}}
\begin{figure}
\centering Example figure.
\caption{\AgentsDel{OLDCAPTION}\AgentsIns{NEWCAPTION}}
\end{figure}
\end{document}''')
                text = self.compile(root)
                self.assertEqual('NEWHEADING' in text, mode != 'reverted')
                self.assertEqual('OLDHEADING' in text, mode != 'applied')
                self.assertEqual('NEWCAPTION' in text, mode != 'reverted')
                self.assertEqual('OLDCAPTION' in text, mode != 'applied')

    def test_external_theorems_and_margin_dimensions_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copyfile(PACKAGE, root / 'papermacros.sty')
            (root / 'main.tex').write_text(r'''\documentclass{article}
\usepackage{amsthm}
\newtheorem*{remark}{Venue remark}
\setlength{\marginparwidth}{37pt}
\setlength{\marginparsep}{11pt}
\usepackage[theorems=external]{papermacros}
\ifdim\marginparwidth=37pt\else\errmessage{Margin width changed}\fi
\ifdim\marginparsep=11pt\else\errmessage{Margin separation changed}\fi
\begin{document}
\begin{remark}Existing venue environment.\end{remark}
\end{document}''')
            self.assertIn('Venue remark', self.compile(root))


class PaletteTest(unittest.TestCase):
    def test_review_colors_have_readable_contrast_on_white(self):
        colors = re.findall(r'\\DeclarePaperAuthor\{[^}]+\}\{[^}]+\}\{[^}]+\}\{([0-9A-F]{6})\}',
                            PACKAGE.read_text())
        self.assertEqual(len(colors), 7)
        def linear(channel):
            channel /= 255
            return channel / 12.92 if channel <= .04045 else ((channel + .055) / 1.055) ** 2.4
        for color in colors:
            rgb = [linear(int(color[i:i+2], 16)) for i in (0, 2, 4)]
            luminance = sum(x*w for x, w in zip(rgb, (.2126, .7152, .0722)))
            self.assertGreaterEqual(1.05 / (luminance + .05), 4.5, color)
