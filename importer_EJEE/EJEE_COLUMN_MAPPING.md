# EJEE column disposition

Generated from the actual source schema. No source table or row is deleted. “Omitted” means excluded from the target PaperLab database; selected resource rows retain every original column in manifest.json. Student data is not exported.

The current database has no tb_chapter table. Textbook chapter numbers are decoded from an explicit configured grp pattern; nodes is the teaching taxonomy and must not be substituted for book chapter order.

## `ex_attendance` (3,888 rows)

| Column | Disposition and reason |
|---|---|
| `exam_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `student_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `status` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |

## `ex_audit` (28 rows)

| Column | Disposition and reason |
|---|---|
| `id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `at` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `actor` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `verb` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `object` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `detail` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |

## `ex_batch` (15 rows)

| Column | Disposition and reason |
|---|---|
| `id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `institution_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `campus_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `name` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `programme` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `academic_year` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |

## `ex_campus` (5 rows)

| Column | Disposition and reason |
|---|---|
| `id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `institution_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `name` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `city` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |

## `ex_correction` (0 rows)

| Column | Disposition and reason |
|---|---|
| `id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `exam_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `sheet_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `student_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `question_number` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `field` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `old_value` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `new_value` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `reason` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `reviewer` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `at` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |

## `ex_exam` (13 rows)

| Column | Disposition and reason |
|---|---|
| `id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `institution_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `name` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `exam_date` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `pattern_version_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `family` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `max_marks` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `target_pct` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `status` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `has_time_log` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `input_method` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `scope_programme` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |

## `ex_exam_question` (861 rows)

| Column | Disposition and reason |
|---|---|
| `id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `exam_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `number` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `subject` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `section` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `qtype` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `max_marks` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `n_options` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `author_difficulty` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `primary_topic_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `resource_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |

## `ex_institution` (2 rows)

| Column | Disposition and reason |
|---|---|
| `id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `name` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `short` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `synthetic` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |

## `ex_key_item` (1,011 rows)

| Column | Disposition and reason |
|---|---|
| `key_version_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `question_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `answer` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `status` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |

## `ex_key_version` (15 rows)

| Column | Disposition and reason |
|---|---|
| `id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `exam_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `version` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `status` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `reason` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `created_at` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |

## `ex_omr_batch` (0 rows)

| Column | Disposition and reason |
|---|---|
| `id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `exam_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `created_at` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `status` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `total` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `done` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `params` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `source` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `finalized_at` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `error` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |

## `ex_omr_exception` (0 rows)

| Column | Disposition and reason |
|---|---|
| `id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `sheet_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `type` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `question_number` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `detail` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `status` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `resolution` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `resolved_by` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `resolved_at` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |

## `ex_omr_sheet` (0 rows)

| Column | Disposition and reason |
|---|---|
| `id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `batch_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `exam_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `orig_name` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `page` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `scan_file` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `aligned_file` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `roll_read` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `student_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `status` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `confidence` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `rotation` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `original` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `blank` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |

## `ex_pattern_version` (4 rows)

| Column | Disposition and reason |
|---|---|
| `id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `institution_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `name` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `version` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `family` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `rules` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `created_at` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |

## `ex_question_tag` (980 rows)

| Column | Disposition and reason |
|---|---|
| `question_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `topic_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `is_primary` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |

## `ex_response_original` (255,414 rows)

| Column | Disposition and reason |
|---|---|
| `exam_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `student_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `question_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `raw` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `source` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |

## `ex_result` (3,969 rows)

| Column | Disposition and reason |
|---|---|
| `run_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `exam_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `student_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `total` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `correct` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `incorrect` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `unanswered` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `partial` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `invalid` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `penalty` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `scored_n` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `subjects` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |

## `ex_score` (284,964 rows)

| Column | Disposition and reason |
|---|---|
| `run_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `student_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `question_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `marks` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `status` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `penalty` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |

## `ex_scoring_run` (13 rows)

| Column | Disposition and reason |
|---|---|
| `id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `exam_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `key_version_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `pattern_version_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `created_at` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `n_students` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `current` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |

## `ex_section` (30 rows)

| Column | Disposition and reason |
|---|---|
| `id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `batch_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `name` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |

## `ex_student` (720 rows)

| Column | Disposition and reason |
|---|---|
| `id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `institution_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `roll_no` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `name` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `campus_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `batch_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `section_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |

## `ex_topic` (40 rows)

| Column | Disposition and reason |
|---|---|
| `id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `subject` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `chapter` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `topic` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |
| `node_id` | Omitted from target: Exam administration, student responses/scoring, or audit state; incompatible with PaperLab extraction statistics and outside textbook import scope. |

## `nodes` (433 rows)

| Column | Disposition and reason |
|---|---|
| `id` | Preserved in selected resource ancestry. Original teaching classification is provenance only; Node 3 supplies all target classification. |
| `parent_id` | Preserved in selected resource ancestry. Original teaching classification is provenance only; Node 3 supplies all target classification. |
| `level` | Preserved in selected resource ancestry. Original teaching classification is provenance only; Node 3 supplies all target classification. |
| `name` | Preserved in selected resource ancestry. Original teaching classification is provenance only; Node 3 supplies all target classification. |
| `position` | Preserved in selected resource ancestry. Original teaching classification is provenance only; Node 3 supplies all target classification. |
| `created_at` | Preserved in selected resource ancestry. Original teaching classification is provenance only; Node 3 supplies all target classification. |
| `uid` | Preserved in selected resource ancestry. Original teaching classification is provenance only; Node 3 supplies all target classification. |

## `paper_items` (884 rows)

| Column | Disposition and reason |
|---|---|
| `id` | Omitted from target: EJEE worksheet composition, not textbook question ownership. |
| `paper_id` | Omitted from target: EJEE worksheet composition, not textbook question ownership. |
| `resource_id` | Omitted from target: EJEE worksheet composition, not textbook question ownership. |
| `position` | Omitted from target: EJEE worksheet composition, not textbook question ownership. |
| `marks` | Omitted from target: EJEE worksheet composition, not textbook question ownership. |
| `section` | Omitted from target: EJEE worksheet composition, not textbook question ownership. |

## `papers` (26 rows)

| Column | Disposition and reason |
|---|---|
| `id` | Omitted from target: EJEE worksheet composition, not textbook question ownership. |
| `kind` | Omitted from target: EJEE worksheet composition, not textbook question ownership. |
| `title` | Omitted from target: EJEE worksheet composition, not textbook question ownership. |
| `instructions` | Omitted from target: EJEE worksheet composition, not textbook question ownership. |
| `duration` | Omitted from target: EJEE worksheet composition, not textbook question ownership. |
| `created_at` | Omitted from target: EJEE worksheet composition, not textbook question ownership. |
| `updated_at` | Omitted from target: EJEE worksheet composition, not textbook question ownership. |
| `category` | Omitted from target: EJEE worksheet composition, not textbook question ownership. |
| `text_pt` | Omitted from target: EJEE worksheet composition, not textbook question ownership. |
| `pattern` | Omitted from target: EJEE worksheet composition, not textbook question ownership. |
| `uid` | Omitted from target: EJEE worksheet composition, not textbook question ownership. |

## `resource_crops` (3 rows)

| Column | Disposition and reason |
|---|---|
| `id` | Inspect for selected resources. Only explicit diagram/solution_diagram roles with validated image/coordinate frames qualify for reuse; question/solution boxes are not isolated diagrams. Preserve linked records. |
| `uid` | Inspect for selected resources. Only explicit diagram/solution_diagram roles with validated image/coordinate frames qualify for reuse; question/solution boxes are not isolated diagrams. Preserve linked records. |
| `resource_id` | Inspect for selected resources. Only explicit diagram/solution_diagram roles with validated image/coordinate frames qualify for reuse; question/solution boxes are not isolated diagrams. Preserve linked records. |
| `resource_uid` | Inspect for selected resources. Only explicit diagram/solution_diagram roles with validated image/coordinate frames qualify for reuse; question/solution boxes are not isolated diagrams. Preserve linked records. |
| `role` | Inspect for selected resources. Only explicit diagram/solution_diagram roles with validated image/coordinate frames qualify for reuse; question/solution boxes are not isolated diagrams. Preserve linked records. |
| `part_no` | Inspect for selected resources. Only explicit diagram/solution_diagram roles with validated image/coordinate frames qualify for reuse; question/solution boxes are not isolated diagrams. Preserve linked records. |
| `seq` | Inspect for selected resources. Only explicit diagram/solution_diagram roles with validated image/coordinate frames qualify for reuse; question/solution boxes are not isolated diagrams. Preserve linked records. |
| `source_id` | Inspect for selected resources. Only explicit diagram/solution_diagram roles with validated image/coordinate frames qualify for reuse; question/solution boxes are not isolated diagrams. Preserve linked records. |
| `src_page` | Inspect for selected resources. Only explicit diagram/solution_diagram roles with validated image/coordinate frames qualify for reuse; question/solution boxes are not isolated diagrams. Preserve linked records. |
| `printed_page` | Inspect for selected resources. Only explicit diagram/solution_diagram roles with validated image/coordinate frames qualify for reuse; question/solution boxes are not isolated diagrams. Preserve linked records. |
| `box_x` | Inspect for selected resources. Only explicit diagram/solution_diagram roles with validated image/coordinate frames qualify for reuse; question/solution boxes are not isolated diagrams. Preserve linked records. |
| `box_y` | Inspect for selected resources. Only explicit diagram/solution_diagram roles with validated image/coordinate frames qualify for reuse; question/solution boxes are not isolated diagrams. Preserve linked records. |
| `box_w` | Inspect for selected resources. Only explicit diagram/solution_diagram roles with validated image/coordinate frames qualify for reuse; question/solution boxes are not isolated diagrams. Preserve linked records. |
| `box_h` | Inspect for selected resources. Only explicit diagram/solution_diagram roles with validated image/coordinate frames qualify for reuse; question/solution boxes are not isolated diagrams. Preserve linked records. |
| `pt_x0` | Inspect for selected resources. Only explicit diagram/solution_diagram roles with validated image/coordinate frames qualify for reuse; question/solution boxes are not isolated diagrams. Preserve linked records. |
| `pt_y0` | Inspect for selected resources. Only explicit diagram/solution_diagram roles with validated image/coordinate frames qualify for reuse; question/solution boxes are not isolated diagrams. Preserve linked records. |
| `pt_x1` | Inspect for selected resources. Only explicit diagram/solution_diagram roles with validated image/coordinate frames qualify for reuse; question/solution boxes are not isolated diagrams. Preserve linked records. |
| `pt_y1` | Inspect for selected resources. Only explicit diagram/solution_diagram roles with validated image/coordinate frames qualify for reuse; question/solution boxes are not isolated diagrams. Preserve linked records. |
| `page_w_pt` | Inspect for selected resources. Only explicit diagram/solution_diagram roles with validated image/coordinate frames qualify for reuse; question/solution boxes are not isolated diagrams. Preserve linked records. |
| `page_h_pt` | Inspect for selected resources. Only explicit diagram/solution_diagram roles with validated image/coordinate frames qualify for reuse; question/solution boxes are not isolated diagrams. Preserve linked records. |
| `render_w_px` | Inspect for selected resources. Only explicit diagram/solution_diagram roles with validated image/coordinate frames qualify for reuse; question/solution boxes are not isolated diagrams. Preserve linked records. |
| `render_h_px` | Inspect for selected resources. Only explicit diagram/solution_diagram roles with validated image/coordinate frames qualify for reuse; question/solution boxes are not isolated diagrams. Preserve linked records. |
| `image_name` | Inspect for selected resources. Only explicit diagram/solution_diagram roles with validated image/coordinate frames qualify for reuse; question/solution boxes are not isolated diagrams. Preserve linked records. |
| `image_sha256` | Inspect for selected resources. Only explicit diagram/solution_diagram roles with validated image/coordinate frames qualify for reuse; question/solution boxes are not isolated diagrams. Preserve linked records. |
| `origin` | Inspect for selected resources. Only explicit diagram/solution_diagram roles with validated image/coordinate frames qualify for reuse; question/solution boxes are not isolated diagrams. Preserve linked records. |
| `created_at` | Inspect for selected resources. Only explicit diagram/solution_diagram roles with validated image/coordinate frames qualify for reuse; question/solution boxes are not isolated diagrams. Preserve linked records. |

## `resource_transcripts` (1 rows)

| Column | Disposition and reason |
|---|---|
| `id` | Preserve selected versions and review/hold metadata as evidence; no unreviewed text replaces source pixels. |
| `uid` | Preserve selected versions and review/hold metadata as evidence; no unreviewed text replaces source pixels. |
| `resource_id` | Preserve selected versions and review/hold metadata as evidence; no unreviewed text replaces source pixels. |
| `version` | Preserve selected versions and review/hold metadata as evidence; no unreviewed text replaces source pixels. |
| `status` | Preserve selected versions and review/hold metadata as evidence; no unreviewed text replaces source pixels. |
| `engine` | Preserve selected versions and review/hold metadata as evidence; no unreviewed text replaces source pixels. |
| `content` | Preserve selected versions and review/hold metadata as evidence; no unreviewed text replaces source pixels. |
| `notes` | Preserve selected versions and review/hold metadata as evidence; no unreviewed text replaces source pixels. |
| `holds` | Preserve selected versions and review/hold metadata as evidence; no unreviewed text replaces source pixels. |
| `created_at` | Preserve selected versions and review/hold metadata as evidence; no unreviewed text replaces source pixels. |

## `resources` (150,926 rows)

| Column | Disposition and reason |
|---|---|
| `id` | Stable resource provenance; group membership and resume identity. |
| `topic_id` | Retain original node ancestry in provenance ONLY. Never seed PaperLab topics. |
| `type` | Provenance and source format evidence; target schema has no subjective code, use unknown if needed. |
| `title` | Source label, original numbering and continuation-order evidence; preserved in manifest. |
| `position` | Order evidence within a group; numeric continuation titles take precedence. |
| `file_name` | Primary source asset under uploads; hash and crop losslessly. |
| `file_orig` | Preserved original filename for traceability. |
| `mime` | Asset validation/provenance; image decoded by Pillow. |
| `question` | Existing transcription as auxiliary evidence only; image remains authoritative. |
| `answer` | Existing answer evidence, checked against source; never synthesize a new answer. |
| `solution` | Existing solution evidence; map with group images, never generate a worked solution. |
| `difficulty` | Provenance ONLY; PaperLab Node 3 reclassifies from imported TeX. |
| `source` | Exact textbook name -> papers.source_institute. |
| `tags` | Provenance ONLY; no automatic topic assignment from EJEE. |
| `exam` | Preserve only: textbooks use exam_type=Textbook, not historical exam labels. |
| `year` | Preserve only: do not invent paper_date from textbook publication or import year. |
| `shift` | Preserve only: no shift for chapter papers. |
| `qtype` | Source format evidence for Node 2; never map subjective to numeric automatically. |
| `created_at` | Preserved in selected resource provenance; omitted from PaperLab because it is EJEE UI/editor state, not archival question content or fresh extraction statistics. |
| `grp` | Exact question–answer join WITH source. Never match by similar titles. |
| `fav` | Preserved in selected resource provenance; omitted from PaperLab because it is EJEE UI/editor state, not archival question content or fresh extraction statistics. |
| `part` | q -> question pages; sol -> ordered solution pages. Other roles require explicit handling. |
| `fingerprint` | Preserved in selected resource provenance; omitted from PaperLab because it is EJEE UI/editor state, not archival question content or fresh extraction statistics. |
| `review` | Preserved in selected resource provenance; omitted from PaperLab because it is EJEE UI/editor state, not archival question content or fresh extraction statistics. |
| `file_alt` | Preserve provenance only; do not silently substitute an altered image. |
| `enhanced` | Preserved in selected resource provenance; omitted from PaperLab because it is EJEE UI/editor state, not archival question content or fresh extraction statistics. |
| `print_meta` | Use box as normalized BODY bounds only; qbox is a fallback. keys/mask/qn are not diagram boxes. Preserve entire JSON. |
| `altered` | Preserved in selected resource provenance; omitted from PaperLab because it is EJEE UI/editor state, not archival question content or fresh extraction statistics. |
| `status` | Preserved in selected resource provenance; omitted from PaperLab because it is EJEE UI/editor state, not archival question content or fresh extraction statistics. |
| `src_doc` | Preserve locator; not a PDF path unless independently resolved. |
| `worksheet_no` | Preserved in selected resource provenance; omitted from PaperLab because it is EJEE UI/editor state, not archival question content or fresh extraction statistics. |
| `uid` | Preserved provenance; not a PaperLab question ID. |

## `source_documents` (1 rows)

| Column | Disposition and reason |
|---|---|
| `id` | Preserve selected crop-source linkage and locator/hash. Resolve and validate asset before coordinate reuse. |
| `uid` | Preserve selected crop-source linkage and locator/hash. Resolve and validate asset before coordinate reuse. |
| `sha256` | Preserve selected crop-source linkage and locator/hash. Resolve and validate asset before coordinate reuse. |
| `file_name` | Preserve selected crop-source linkage and locator/hash. Resolve and validate asset before coordinate reuse. |
| `title` | Preserve selected crop-source linkage and locator/hash. Resolve and validate asset before coordinate reuse. |
| `page_count` | Preserve selected crop-source linkage and locator/hash. Resolve and validate asset before coordinate reuse. |
| `created_at` | Preserve selected crop-source linkage and locator/hash. Resolve and validate asset before coordinate reuse. |

## `sqlite_sequence` (7 rows)

| Column | Disposition and reason |
|---|---|
| `name` | Omitted from target: SQLite internal sequence; target generates its own IDs. |
| `seq` | Omitted from target: SQLite internal sequence; target generates its own IDs. |

## `strokes` (14 rows)

| Column | Disposition and reason |
|---|---|
| `resource_id` | Omitted from target: Handwritten annotation state; not printed source content. |
| `data` | Omitted from target: Handwritten annotation state; not printed source content. |
