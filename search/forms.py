from django import forms



class QueryForm(forms.Form):
    query_string = forms.CharField(label="Search term(s)/phrase",
                                   help_text="Enter the full search string to match. An exact match is required for your Promoted Results to be displayed, wildcards are NOT allowed.",
                                   required=True)
