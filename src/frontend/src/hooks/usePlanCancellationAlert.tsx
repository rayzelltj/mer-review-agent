import { useCallback } from 'react';
import { PlanStatus } from '../models';
import { APIService } from '../api/apiService';

interface UsePlanCancellationAlertProps {
  planData: any;
  onNavigate: () => void;
}

/**
 * Custom hook to handle plan cancellation alerts when navigating during active plans
 */
export const usePlanCancellationAlert = ({
  planData,
  onNavigate
}: UsePlanCancellationAlertProps) => {
  const apiService = new APIService();

  /**
   * Check if a plan is currently active/running
   */
  const isPlanActive = useCallback(() => {
    return planData?.plan?.overall_status === PlanStatus.IN_PROGRESS;
  }, [planData]);

  /**
   * Handle the confirmation dialog and plan cancellation
   */
  const handleNavigationWithConfirmation = useCallback(async () => {
    if (!isPlanActive()) {
      // Plan is not active, proceed with navigation
      onNavigate();
      return;
    }

    // Show confirmation dialog
    const userConfirmed = window.confirm(
      "If you continue, the plan process will be stopped and the plan will be cancelled."
    );

    if (!userConfirmed) {
      // User cancelled, do nothing
      return;
    }

    try {
      // User confirmed, cancel the plan
      await apiService.cancelRun(planData?.plan?.id);

      // Navigate after successful cancellation
      onNavigate();
    } catch (error) {
      console.error('❌ Failed to cancel plan:', error);
      // Show error but still allow navigation
      alert('Failed to cancel the plan properly, but navigation will continue.');
      onNavigate();
    }
  }, [isPlanActive, onNavigate, planData, apiService]);

  return {
    isPlanActive,
    handleNavigationWithConfirmation
  };
};

export default usePlanCancellationAlert;
