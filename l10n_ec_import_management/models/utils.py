def records_action(records, name):
    """Window action opening ``records`` (form view when there is only one)."""
    action = {
        "type": "ir.actions.act_window",
        "name": name,
        "res_model": records._name,
        "domain": [("id", "in", records.ids)],
        "views": [(False, "list"), (False, "form")],
        "context": {"create": False},
    }
    if len(records) == 1:
        action.update(res_id=records.id, views=[(False, "form")])
    return action
