class BotflowsDataTable:
    def __init__(self, rows):
        self.rows = rows or []
        self.headers = list(rows[0].keys()) if rows else []

    def __iter__(self):
        return iter(self.rows)

    # def to_log_string(self):
    #     return render_datatable(self.rows)

    def get_column_values(self, column_name):
        return [row.get(column_name, "") for row in self.rows]
