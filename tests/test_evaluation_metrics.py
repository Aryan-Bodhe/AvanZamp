from invoicedesk.application.evaluation import score_case, aggregate


def test_empty_holdout_never_passes_release_gate():
    result = aggregate([], 30)
    assert result['field_accuracy'] is None
    assert not result['extraction_gate_passed'] and not result['release_accepted']
    assert result['total_token_cost_usd'] is None


def test_metrics_count_incorrect_approval_and_partial_rows():
    expected = dict(fields={'invoice_number':'A','total':'100.00'},
                    line_items=[{'description':'Service'},{'description':'Charge'}],safe_to_recommend_approval=False)
    report = dict(extraction={'invoice_number':'A','total':'100','line_items':[{'description':'Service'}]},
                  decision={'outcome':'AUTO_APPROVE'}, metrics={'processing_ms':120,'usage':{'input_tokens':10},'token_cost_usd':'0.012'})
    score = score_case(expected,report)
    assert score['field_correct'] == 2 and score['row_complete'] == 1
    result = aggregate([score],1)
    assert result['incorrect_auto_approvals'] == 1
    assert result['row_completeness'] == .5
    assert result['total_token_cost_usd'] == '0.012'
    assert not result['extraction_gate_passed']
