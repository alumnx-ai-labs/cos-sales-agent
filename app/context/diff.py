from app.context.models import DICT_FIELDS, LIST_FIELDS, ContextChange, ThreadContext


def diff_context(previous: ThreadContext, new: ThreadContext, source_email_id: str) -> list[ContextChange]:
    changes: list[ContextChange] = []

    for field in LIST_FIELDS:
        previous_values = {item.value for item in getattr(previous, field)}
        new_values = {item.value for item in getattr(new, field)}

        for added in new_values - previous_values:
            changes.append(
                ContextChange(type="ADDED", field=field, detail=added, source_email_id=source_email_id)
            )
        for removed in previous_values - new_values:
            changes.append(
                ContextChange(type="REMOVED", field=field, detail=removed, source_email_id=source_email_id)
            )

    for field in DICT_FIELDS:
        previous_dict: dict = getattr(previous, field)
        new_dict: dict = getattr(new, field)
        all_keys = set(previous_dict) | set(new_dict)
        for key in all_keys:
            old_value = previous_dict.get(key)
            new_value = new_dict.get(key)
            if old_value == new_value:
                continue
            if old_value is None:
                changes.append(
                    ContextChange(
                        type="ADDED", field=f"{field}.{key}", detail=str(new_value), source_email_id=source_email_id
                    )
                )
            elif new_value is None:
                changes.append(
                    ContextChange(
                        type="REMOVED", field=f"{field}.{key}", detail=str(old_value), source_email_id=source_email_id
                    )
                )
            else:
                changes.append(
                    ContextChange(
                        type="UPDATED",
                        field=f"{field}.{key}",
                        detail=f"{old_value} -> {new_value}",
                        source_email_id=source_email_id,
                    )
                )

    if previous.summary != new.summary and new.summary:
        changes.append(
            ContextChange(type="UPDATED", field="summary", detail=new.summary, source_email_id=source_email_id)
        )

    return changes
